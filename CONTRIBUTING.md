# Contributing

Thank you for helping improve Vector 1A.

1. Create a branch from `main`.
2. Keep changes narrowly scoped and preserve deterministic queue timing.
3. Add or update tests for motion, timing, parsing, or output behavior.
4. Install test tools with `python -m pip install ".[test]"`, then run
   `python -m pytest -q`. This runs both unittest classes and standalone test functions.
5. Open a pull request describing the observed behavior and verification setup.

Never test an unreviewed change on connected stimulation hardware. Use ReStim's
graphical display with hardware disconnected first. Reports should omit private
media filenames, network addresses, and other personal information.
