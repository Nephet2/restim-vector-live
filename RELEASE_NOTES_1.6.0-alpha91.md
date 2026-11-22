# Vector 1A v91

Builds on v90 (rest behaviour, output smoothing and safety fixes).

## Pop-out Signal Quality window
- **Live diagnostics → Signal Quality** has a **Pop out** button that opens the same view in its own movable, resizable window.
- The window starts with the tab's output, time window and axis selections, and keeps updating while the Live diagnostics section is collapsed or scrolled away, so the effect of an adjustment (for example Frequency or Volume response) can be watched as it is made.
- **Keep on top** keeps it above the main Vector window. Pressing Pop out again brings the open window forward.
- Like the tab, it only shows successful T-code socket writes; it does not change settings or output.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
