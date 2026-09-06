# Vector 1A 1.6.0-alpha72

## ReStim dropout hardening

- Primary and prostate ReStim outputs now use independent dedicated sender threads.
  Socket I/O no longer runs on Vector's deterministic calculation/release thread.
- Each output lane is bounded to one pending immutable frame. When a destination is
  slow, newer authoritative frames replace older pending frames instead of building a
  delayed replay backlog.
- Frames older than 250 ms are discarded. Vector never fabricates replacement motion
  and never replays stale T-code after a dropout.
- A blocked or failing ReStim A connection cannot stall ReStim B, the MFP listener, the
  media clock, Director API, or Vector's fixed-cadence engine.
- WebSocket reconnection remains independent per instance. After reconnection, Vector
  sends the existing zero-volume neutral frame first and resumes only when a fresh
  authoritative output frame is available. It does not press or emulate ReStim Start.

## Diagnostics

- Successful-send age and cadence, socket state, send failures, reconnect attempts and
  reconnect successes are tracked independently for both ReStim instances.
- Sender health includes worker liveness, pending state, replaced-frame count,
  stale-frame count and socket-send duration.
- Every two seconds the console prints concise `RESTIM A` and `RESTIM B` lines including
  MFP `source_age`, media-clock state, engine state, output progress and loop liveness.
- The MFP stale-input watchdog logs both entry and recovery transitions without
  restarting MFP or generating substitute T-code.

## Compatibility

All alpha71 Director, timeline, focus, spatial-gain, modifier, controller, routing and
media-clock behavior is preserved.
