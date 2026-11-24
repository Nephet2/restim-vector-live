# Vector 1A v93

Builds on v92 (live display no longer freezes when a dropdown is opened).

## Fix: garbled characters in the interface
- Some labels, buttons and status messages showed three-character garbage in place of an ellipsis, dash, multiplication sign or similar symbol, for example on the **Browse…** buttons, the **Captured?** column of the Director profiles, the top spatial model names (**Top — Moving Focus**), the tempo status (**Tempo authored ×1.0**) and the controller key help.
- 60 places in the interface and 15 in the README now show the intended characters (…, —, –, ×, ±, −, •, ·, →).
- Display text only: saved settings and the Director API are unchanged. A new test fails if this kind of encoding damage returns.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
