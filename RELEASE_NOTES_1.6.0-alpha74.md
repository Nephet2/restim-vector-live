# Vector 1A 1.6.0-alpha74

This corrects alpha73's generated-motion envelope to follow funscript-style point timing:

- L0 may use the full 0.0–1.0 range.
- Minimum plan travel remains 0.10.
- One-way `stroke_duration_ms` replaces cycles per minute.
- Valid one-way stroke durations are 125–3000 ms, equivalent to 240–10 complete cycles per minute when continuously traversing both endpoints.
- Speed is therefore defined by both travel distance and time, rather than a cadence value divorced from stroke length.

All alpha73 generated-motion authority, validation, lifecycle and telemetry features remain present.
