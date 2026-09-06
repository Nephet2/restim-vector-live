# Vector 1A 1.6.0-alpha69

## Modifier commissioning refinement

- Collapses Alpha68's redundant Stroke Amplitude Scale + Global Range Scale into one **Stroke Range** control.
- Keeps **Position Bias** and **Curve Smoothing**.
- Explicitly clamps transformed L0 to ReStim's normalized 0..1 range.
- Changes the default modifier transition from 0.75 s to **0.20 s** based on commissioning feedback.
- Adds a manual **Temporary Tempo Window** with 0.5x / 1x / 2x and a configurable duration.
- True 2x tempo samples the loaded full authored funscript timeline so it can use future authored positions instead of reaching an endpoint early and waiting.
- Tempo restoration rejoins the current authored L0 through the configured transition ramp.
- Tempo remains manual commissioning only; no Gwendolyn/Director modifier tools are exposed yet.
- Existing standalone Vector architecture and MFP -> Vector -> ReStim path remain intact.

Validation: **167 tests passed**.
