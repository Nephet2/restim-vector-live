# Vector 1A v94

Builds on v93 (garbled interface text repaired).

## Smoother Signal Quality plot
- The Signal Quality traces (in Live diagnostics and in the pop-out window) are now anti-aliased: drawn at twice the size and smoothed down, so slopes no longer show stair steps. Axis labels stay as sharp native text.
- Each pixel column now shows the lowest and highest values it covers, as an oscilloscope does. Fast changes in the 30 s window appear as a clean band instead of a jittery zig-zag, and every peak stays visible.
- Redrawing is about three times faster than before (about 13 ms instead of 41 ms for three axes over 30 s at pop-out size), and it runs on the display thread, not the output engine.
- Needs the bundled Pillow (included for Python 3.13 x64). Without it the plot is drawn as before, with the per-column reduction.

## Maintenance: output settings defined in one place
- The output settings sent to the composer were listed by hand in three places. They are now built from one definition, so a setting added later cannot be missed.
- **Keyframe arcs** and the four pulse **Damping (s)** values were only passed on by their own controls. They are now followed like every other output setting. Nothing else changes them today, so this makes no difference in use.
- A new test checks that every output setting takes effect as soon as it changes.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
