# Vector 1A v89

- Pulse Frequency and Pulse Width damping now support up to 30 seconds. Frequency and Pulse Rise Time support up to 10 seconds.
- Fresh profiles use the tuned response curves and motion settings, including ReStim Original motion, 2.95 seconds of look-ahead and damping of 3 s for Frequency, 10 s for Pulse Frequency, 3 s for Pulse Rise Time and 10 s for Pulse Width.
- Existing profiles retain their saved settings when copied into the new installation. The public defaults contain response tuning only. Device addresses, credentials and local paths are configured separately.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
