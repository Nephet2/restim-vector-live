# Vector 1A 1.6.0-alpha77

Alpha77 adds optional curated custom events for local Director companions such as
Gwendolyn. It adapts the deterministic event runtime and recipe catalogue developed in
the Senorgif33 fork while keeping Vector's current timeline and Director architecture.

## Curated event actions

The Director API can trigger ten named recipes: Tease, Throb, Calm, Intensity build,
Release, Tranquil, Pulse wobble, Pulse-frequency shift, Pulse-width shift and Volume
shift. Recipes are temporary overlays on the existing signal and automatically expire.

- Enable **Allow curated Director custom events** in Vector's Director window.
- `POST /v1/event/trigger` accepts a catalogue ID and optional duration.
- `POST /v1/event/cancel` immediately removes all event overlays.
- `GET /v1/state` reports whether events are enabled, active and recently triggered.

Vector rejects unlisted recipes and durations outside 2–30 seconds. Stronger inherited
volume modulation recipes use reduced amplitudes in this Director-facing profile. The
larger countdown, extract, hard-stop and test recipes are present for attribution and
future review but cannot be invoked through this API.

Neutral and Stop both clear active events. The feature and the Director API remain off
by default, and Vector remains fully usable without Gwendolyn or another companion.

## Validation

The complete suite passes: 241 tests plus 12 parameterized subtests. Coverage includes
recipe parsing and expansion, overlap and expiry, API routing, operator opt-in, allowlist
validation, duration bounds and curated parameter overrides.
