# Vector 1A 1.6.0-alpha61

Director visibility and grounded stop foundation.

## Added

- `POST /v1/stop` — true zero-output stop. This is distinct from Neutral; it sets output volume to zero and leaves the engine stopped until Resume.
- `signal` block in `GET /v1/state` with deterministic live-L0 observations:
  - activity: active / hold / lull
  - input age
  - current position and direction
  - recent local range and amplitude
  - mean recent stroke amplitude
  - reversal rate
  - coarse lower / middle / upper script focus
  - relative energy score and semantic band: relaxing / moderate / challenging / testing
- Director API version 0.7.

## Existing look-ahead retained

Alpha60 already exposed Vector's deterministic queued future through the `future` state block. Alpha61 retains this short look-ahead (normally about the configured Vector look-ahead, currently ~2 s) and complements it with richer live signal semantics.

The energy band is intentionally labelled as relative live-script energy. It is not an assertion of absolute physical output intensity.

## Architecture

This remains entirely Vector-owned and AI-independent. No Ollama, TTS, STT or Gwendolyn dependency has been added to Vector.
