# Vector 1A 1.6.0-alpha65

- Adds authoritative read-only media clocks for VLC and MPC, plus Auto mode (VLC first, MPC fallback).
- Adds automatic `.funscript` discovery from the playing media basename, first beside the media and then in configured script-library folders.
- Direct-player seeks update funscript timeline position immediately; no MFP pattern reacquisition is required.
- Adds timeline media metadata and `clock_authoritative` to `/v1/state`.
- Keeps MFP pattern sync and Manual preview as fallbacks.
- Does not control the player and does not use the loaded funscript to drive or modify Vector output.
- 156 automated tests passing.
