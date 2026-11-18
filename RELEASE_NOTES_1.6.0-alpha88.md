# Vector 1A v88

- **Handy** adds Wi-Fi device control, manual motion and timed funscript playback on supported devices. See the [Handy setup guide](HANDY-INTERFACE.md).
- **VacuGlide** adds manual and scripted control, including funscript following. Handy motion and VacuGlide intensity can be operated together from the [Motion + Intensity desk](MOTION-INTENSITY.md).
- **Response controls** add independent damping, timing (±500 ms) and stroke phase (±180°) for generated primary ReStim carrier frequency, pulse frequency, rise time and width. The readouts show the applied offset and composed command.
- **Playback** adds direct MPC-HC and HereSphere input with associated funscript discovery and manual loading, plus experimental DeoVR playback-clock input. Direct playback supports optional keyframe arcs in ReStim Original mode.
- **Motion tools** add stroke-range preservation, stroke timing variation and passage sequences.

## Installation

Extract the Windows source ZIP into a new folder and open `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This is an alpha prerelease. Automated tests exercise the control paths with simulated inputs and devices. The release includes a SHA-256 checksum for the source ZIP.
