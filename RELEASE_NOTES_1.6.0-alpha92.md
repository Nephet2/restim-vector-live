# Vector 1A v92

Builds on v91 (pop-out Signal Quality window). Thanks to the user who reported this with reproduction steps and a diagnosis.

## Fix: live display froze after opening a dropdown
- On Python 3.10, opening any dropdown (for example a spatial model or custom spatial curve) raised `KeyError: 'popdown'` during the display refresh. The refresh then stopped for the rest of the session: the Volume response, Frequency and pulse bars, the E1–E4 display and the Signal Quality graph froze until Vector was restarted. Output to ReStim was not affected.
- The range bars and the Handy and output panels no longer use the call that failed.
- The display refresh now always continues to its next update, so an error in one display step can no longer stop the live display, or the Civet pressure-fault check that runs with it, for the rest of the session.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
