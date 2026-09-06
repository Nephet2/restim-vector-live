# Vector 1A 1.6.0-alpha66

Direct media-clock reliability commissioning release.

## Changes

- Direct VLC/MPC clocks are now polled continuously from Vector's normal UI refresh loop, even when the Funscript Timeline window is closed.
- Player polling remains asynchronous and internally rate-limited (about 0.45 s minimum interval), so it does not block the signal engine.
- Between authoritative player samples, a playing clock is extrapolated from the last timestamp and playback rate. Paused/stopped clocks do not advance.
- `/v1/state` timeline metadata now includes `media_sample_age_seconds` for commissioning diagnostics.
- Existing direct seek behavior, automatic funscript discovery, MFP pattern sync fallback, and read-only timeline architecture are preserved.

## Safety / architecture

The media clock and loaded funscript remain observation-only. They do not drive or transform live T-code in this release.
