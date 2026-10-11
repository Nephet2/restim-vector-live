# Vector 1A 1.6.0-alpha78

Alpha78 refines transitions introduced in the current Director-controlled build.

- Smooths bottom-focus changes instead of switching their spatial weighting abruptly.
- Interpolates secondary focus weights through the transition window.
- Keeps generated prostate-focused motion continuous while a focus transition is underway.
- Adds regression coverage for bottom-focus and generated-motion continuity.

All existing alpha77 curated-event controls, validation limits and operator opt-ins remain unchanged.

