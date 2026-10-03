#!/usr/bin/env python3
"""Exercise the real generator and PNG writer; MOGRIFY/SOONG_ZIP select tools."""

import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import unittest
import zipfile
import zlib


BOOTANIMATION = Path(__file__).resolve().parents[1]


def png_chunks(data):
    """Read and validate chunks without changing pixels or color metadata."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    chunks = []
    position = 8
    while position < len(data):
        length = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        checksum = struct.unpack_from(">I", data, position + 8 + length)[0]
        if zlib.crc32(kind + body) & 0xffffffff != checksum:
            raise ValueError("invalid PNG chunk checksum")
        chunks.append((kind, body))
        position += length + 12
    if position != len(data) or chunks[-1][0] != b"IEND":
        raise ValueError("invalid PNG length")
    return chunks


def volatile_chunk(chunk):
    kind, body = chunk
    return kind == b"tIME" or (kind == b"tEXt" and
                              body.split(b"\0", 1)[0] in
                              {b"date:create", b"date:modify"})


class BootanimationGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mogrify = os.environ.get("MOGRIFY") or shutil.which("mogrify")
        cls.soong_zip = os.environ.get("SOONG_ZIP") or shutil.which("soong_zip")
        cls.generator = Path(os.environ.get("BOOTANIMATION_GENERATOR",
                                             BOOTANIMATION / "gen-bootanimation.sh"))
        if not cls.mogrify or not cls.soong_zip:
            raise unittest.SkipTest("real mogrify and soong_zip are required")
        # Use committed animation frames rather than a substitute PNG encoder.
        # Two frames per part keep this host regression small.
        cls.frames = {}
        per_part = {}
        with tarfile.open(BOOTANIMATION / "bootanimation.tar") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".png"):
                    continue
                part = member.name.split("/", 1)[0]
                if per_part.get(part, 0) < 2:
                    cls.frames[member.name] = archive.extractfile(member).read()
                    per_part[part] = per_part.get(part, 0) + 1
        if not cls.frames:
            raise ValueError("committed animation frames absent")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_generator(self, name, mtime):
        work = self.root / name
        work.mkdir()
        archive_path = work / "frames.tar"
        with tarfile.open(archive_path, "w") as archive:
            for filename, data in self.frames.items():
                member = tarfile.TarInfo(filename)
                member.mode = 0o644
                member.mtime = mtime
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        output = work / "bootanimation.zip"
        subprocess.run(["bash", str(self.generator), str(output), str(work / "gen"),
                        str(archive_path), str(BOOTANIMATION / "desc.txt"),
                        self.mogrify, self.soong_zip, "64", "64", "false"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with zipfile.ZipFile(output) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        return output.read_bytes(), members

    def test_distinct_file_and_invocation_times_produce_identical_bytes(self):
        first, first_members = self.run_generator("first", 978307200)
        # PNG tIME has one-second precision; ensure a different writer time.
        time.sleep(1.1)
        second, second_members = self.run_generator("second", 1609459200)
        self.assertEqual(first, second)
        self.assertEqual(first_members, second_members)
        self.assertEqual(set(first_members), {*self.frames, "desc.txt"})
        for filename in self.frames:
            self.assertFalse(any(volatile_chunk(chunk) for chunk in
                                 png_chunks(first_members[filename])), filename)

    def test_image_and_color_chunks_match_the_original_writer(self):
        _, generated = self.run_generator("generated", 978307200)
        original = self.root / "original"
        for filename, data in self.frames.items():
            path = original / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        subprocess.run([self.mogrify, "-resize", "64x21", "-colors", "256",
                        *(str(original / filename) for filename in self.frames)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for filename in self.frames:
            expected = [chunk for chunk in png_chunks((original / filename).read_bytes())
                        if not volatile_chunk(chunk)]
            actual = png_chunks(generated[filename])
            self.assertEqual(actual, expected, filename)
            self.assertTrue(any(kind == b"IDAT" for kind, _ in actual))
            self.assertTrue(any(kind in {b"sRGB", b"gAMA", b"cHRM", b"iCCP"}
                                for kind, _ in actual), filename)


if __name__ == "__main__":
    unittest.main()
