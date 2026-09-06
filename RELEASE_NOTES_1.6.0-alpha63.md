# Vector 1A 1.6.0-alpha63

## Director stop/resume state-machine fix

- `POST /v1/stop` now latches Vector output off until an explicit `POST /v1/resume`.
- Incoming MFP/T-code may continue to be received and observed while output is stopped; it cannot silently reactivate output.
- `/v1/state` now exposes separate `engine_state`, `input_state`, and `output_enabled` fields.
- Engine diagnostics report control-state changes immediately rather than waiting for the next scheduler tick, fixing false post-stop `Running` verification.
- `POST /v1/resume` clears stale queued output, re-enables output, and returns the engine to `Buffering` until fresh/due signal is available.

This release does not change signal generation, ReStim mapping, semantic observer behaviour, or Gwendolyn Director policy.
