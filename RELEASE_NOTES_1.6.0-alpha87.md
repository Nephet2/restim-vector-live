# Vector 1A v87: refined interface and semantic tempo

- Fixed Start / Resume, Neutral and Stop controls, navigation menus and section shortcuts.
- Compact response panel and model-specific spatial controls.
- Read-only connection diagnostics distinguish configured addresses from live health. Duplicate Primary/Prostate endpoints are rejected.
- Separate input pipeline, immutable output-settings snapshots, output composition and settings codec, with captured v85 regression fixtures.
- Temporary authored L0 tempo choices of 0.5x, 1x and 2x in Semantic profiles and the Director API. Companion applications must expose corresponding tools; this download does not update Gwendolyn itself.
- Windows source ZIP bundles Bleak 3.0.2, its Windows runtime dependencies and Pillow 12.0.0 for Python 3.13 x64. Includes an import-only Civet dependency checker.

## Installation

Extract the full source-windows ZIP into a new folder and run start-vector1a.bat with Python 3.13 x64 installed. Keep dependencies beside the launcher. Bundled dependencies need no system-wide package installation.

Close Vector before copying your previous profile/Vector1A/settings.json into the new folder. The archive contains no personal profiles, device readings or session logs. Public ReStim port defaults remain 12346 and 12350; intensity matching and speed-linked optional effects remain off for new profiles. Saved choices are retained.

## Validation

The publishing workflow runs Windows tests on Python 3.11, 3.13 and 3.14 before building. It verifies locked dependency hashes, inspects the ZIP for private runtime files, imports the bundled Bluetooth backend without discovery and smoke-tests the extracted UI without output. A SHA-256 file accompanies the source ZIP.

Automated tests cover engine behavior, saved settings, loopback transport and UI layout. They do not establish physical stimulation behavior or Bluetooth pairing with a particular device. This remains an alpha prerelease, following the existing release series.
