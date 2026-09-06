# Vector 1A 1.6.0-alpha50

## Experimental Director-ready build

Alpha 51 adds an optional local Director API while keeping Vector fully standalone. No AI, voice, Ollama, SillyTavern, GPU or cloud service is required.

### Added

- Loopback-only Director API, disabled by default.
- Read-only `/v1/state` and `/v1/capabilities` endpoints.
- Bounded high-level commands for Preset A/B/Baseline, Rolling Variety on/off, and Neutral.
- Director status and configuration window in the Vector toolbar.
- Capability metadata that explicitly reports raw axis and volume authority as unavailable in this release.
- Standard-library smoke-test client under `tools/director_smoke_test.py`.

### Architecture

Future axis and limited-volume authority is reserved for a separate Vector-owned signal overlay after authored/generated routing and before final output clamping. Alpha 51 does not yet expose those controls.

### Safety / compatibility

- Director API binds to loopback only in this release.
- Existing signal-generation mathematics, deterministic queueing, authored-axis routing and session startup are unchanged.
- The Director interface is optional and off by default.
