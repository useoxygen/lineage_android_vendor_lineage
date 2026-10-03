Run the producer regression with real host tools:

```sh
MOGRIFY=/path/to/mogrify SOONG_ZIP=/path/to/soong_zip \
  python3 -m unittest discover -s bootanimation/tests -p 'test_*.py' -v
```

The fixture uses committed animation frames. It changes source file mtimes and
PNG writer invocation times, compares complete generated ZIP bytes, validates
PNG CRCs, and compares every remaining image/color chunk with the original
resize-and-palette writer. It requires actual ImageMagick and soong_zip; it does
not normalize either output for the reproducibility assertion. Full platform
clean/warm equivalence remains a separate acceptance check.
