# Vector 1A 1.6.0-alpha84

Combines the Custom Curves preview 2 features and responsive connection fixes with the secondary carrier-frequency correction.

## Changes
- Both primary and secondary/prostate ReStim outputs send carrier frequency on C0, matching ReStim defaults.
- The Frequency send checkbox controls C0 on both outputs.
- Includes the editable four-phase E1-E4 Custom Curves, presets, interpolation, live editing, 3D preview and named profiles from the preview.
- Retains nonblocking connection controls and health reads, including smooth UI operation when a ReStim endpoint is unavailable. Edit Custom curves remains beside Spatial model.

## Install
This is a Python source release. Extract the entire source-windows ZIP and run start-vector1a.bat. Python 3.11+ is required; Python 3.13 x64 is recommended for the bundled Pillow dependency. No portable executable is included.

Close Vector and copy profile/Vector1A/settings.json from your existing installation into the matching location in the new folder to retain settings. Public downloads contain no personal settings.

If you used the F0 workaround, set the secondary ReStim carrier-frequency mapping back to C0.

## Validation
The carrier fix passed 18 targeted network/output-control tests, including all 16 checkbox combinations, and the normal entry-point smoke test. The user confirmed that carrier frequency now updates in the secondary ReStim instance. The complete local suite passed: 286 tests and 12 subtests on Windows / Python 3.13. No physical-hardware output was exercised by automated tests.

This source build supersedes the earlier preview packages. It is a new source package, not a restoration of any earlier alpha84 executable.
