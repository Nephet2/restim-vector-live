# Vector 1A 1.6.0-alpha67

Focused MPC direct-clock correction.

- Corrects MPC-HC/MPC-BE `variables.html` numeric `position` and `duration`: those values are milliseconds and are now converted to seconds.
- Uses MPC numeric state codes for play/pause/stop so localized `statestring` text cannot break interpolation.
- Adds raw MPC position/duration and position-source diagnostics to timeline state.
- Adds direct-clock health: live/checking/paused/stale/disconnected/no-position.
- A playing direct clock that does not advance for two seconds is no longer treated as authoritative.
- Auto mode keeps a small MFP/L0 history available as a stale-clock fallback.
- Timeline UI shows the live parsed position, raw MPC position, source and clock health.

The funscript timeline remains read-only and does not drive Vector output.
