# Vector 1A 1.6.0-alpha73

## Optional Gwendolyn-generated incoming motion

- Adds a loopback Director endpoint for bounded high-level motion plans.
- Vector validates every plan and generates L0 deterministically at 25 Hz; the Director cannot submit raw axis samples.
- Authored T-code remains the default source.
- Generated motion supports explicit hold, resume, and return-to-authored controls.
- Vector Stop immediately clears generated-motion authority before stopping output.
- `/v1/state` reports the active motion source and exact validated plan.

The permitted plan envelope is deliberately fixed in Vector: sine/triangle/breathing patterns, the full L0 0.0–1.0 range with at least 0.10 travel, 125–3000 ms per one-way stroke, 1–15 second transitions, and 30–600 second plan windows. Point-to-point stroke duration is used instead of a fixed cycles-per-minute bound because funscript speed depends on both distance and time.
