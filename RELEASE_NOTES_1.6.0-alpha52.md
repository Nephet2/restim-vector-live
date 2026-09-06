# Vector 1A 1.6.0-alpha52

Alpha 52 adds the first semantic Director control layer while keeping Vector fully standalone and AI-independent.

## Added

- User-captured Texture profiles with perceptual labels:
  - Smoothest
  - Smooth
  - Normal
  - Rough
  - Roughest
- User-captured Variation profiles:
  - Still
  - Subtle
  - Normal
  - Lively
  - Wild
- Primary spatial semantic choices:
  - Top — Moving Focus
  - Top — Depth Spread
- Secondary spatial semantic state:
  - Bottom Focus, representing the existing secondary/prostate generated path.
- Director API v0.2 semantic endpoints:
  - `POST /v1/semantic/texture`
  - `POST /v1/semantic/primary-spatial`
  - `POST /v1/semantic/secondary-spatial`
  - `POST /v1/semantic/variation`
- Director state now reports the semantic state and only advertises captured Texture/Variation labels as available.
- New **Semantic profiles** window under Director API for capturing and applying perceptual profiles.

## Design

Texture and Variation are user-calibrated rather than hard-coded. The labels describe what the user perceives; Vector stores the underlying existing settings. This avoids pretending that one fixed set of pulse/frequency/crossover values will feel the same for every setup.

Primary Spatial maps directly onto Vector's existing proven Moving Focus and Depth Spread models. Depth Spread retains its existing precedence/bypass behaviour inside Vector.

No signal-generation mathematics, MFP authored-axis routing, synchronization, startup orchestration, or ReStim connection behaviour is replaced by the Director layer.

## Still reserved

- bounded Director volume overlay / Hold Your Nerve authority
- bounded direct axis overlays
- additional secondary spatial profiles

These remain future Vector-owned capabilities rather than raw LLM control.
