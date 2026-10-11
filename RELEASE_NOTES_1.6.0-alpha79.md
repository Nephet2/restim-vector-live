# Vector 1A 1.6.0-alpha79

This release adds Howl-inspired conversion to the live MFP-to-ReStim bridge,
with controls for tuning its sensation and keeping intensity consistent when
switching spatial models. It also includes the Desktop build's Civet pressure
attenuation controls.

## Changes

- Howl Positional and Howl Dynamic spatial modes, available in the main controls
  and the Gwendolyn/Director Primary spatial choices. Director state reports the
  selected mode correctly.
- Adjustable sensation width, dynamic panning, smoothing, slow-motion boost,
  pulse frequency range, frequency balance A/B, amplitude scaling, positional
  effect strength and low-frequency thump strength.
- Match intensity across spatial modes is enabled by default. Moving Focus,
  Depth Spread and both Howl modes share a continuous movement-based volume
  envelope. Disable this option to restore their individual volume behaviour.
- Independent Send TCode controls for carrier Frequency, Pulse frequency,
  Pulse rise time and Pulse width. Disabled axes are omitted from primary and
  secondary outputs, including authored overrides and manual previews.
- Startup automatically starts the MFP listener, connects Primary ReStim and
  resumes the engine. It retries the connection if ReStim is unavailable. This
  can be disabled in Session startup; pressing Stop still latches output off.
- Optional Civet pressure attenuation with thresholds, response/recovery
  timing, stale-data suppression and a fault latch. Pressure control starts
  disabled and requires explicit connection and enabling.
- Repaired corrupted interface characters and changed roll-up buttons to +/−.
- The Windows launcher keeps settings in the extracted folder's
  `profile/Vector1A/settings.json`.

## Setup and compatibility

Extract the Windows ZIP and run `start-vector1a.bat` with Python 3.11 or newer.
For Civet Bluetooth support, install dependencies from the extracted folder
with `python -m pip install .`; this installs the pinned Bleak dependency.
The release contains no personal settings or Bluetooth addresses.

When upgrading, configure MFP/ReStim connections or copy your previous
`profile/Vector1A/settings.json` into the new folder. A first launch uses the
new defaults, including automatic ready startup and intensity matching.

Howl pulse output requires linear ReStim P0 mapping of 1–100 Hz and P1 mapping
of 3–20 carrier cycles. Unchecking Send TCode leaves ReStim's last received
value in place: set the desired static value in ReStim afterward. Carrier
frequency and pulse rise remain Vector/ReStim controls.

Read [Howl setup](HOWL-SETUP.md) and [Civet pressure controls](CIVET_PRESSURE.md)
for details. The Howl modes adapt streamed L0, not Howl's full file playback,
multi-axis processing or effects. Identical volume commands do not guarantee
identical perceived intensity across electrode patterns and pulse settings.

## Validation

258 pytest tests and 12 subtests passed on Windows with Python 3.13. Source
compilation and release archive checks passed. Existing alpha78 regression
tests are retained. No physical stimulation hardware was used for release
validation.
