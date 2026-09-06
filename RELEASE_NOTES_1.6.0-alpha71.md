# Vector 1A 1.6.0-alpha71

## Relative Stroke Range Director control

- Added `/v1/modifier/stroke-range` with `narrower`, `wider`, and `restore` actions.
- Relative step is owned by Vector: 0.10 per request.
- Bounds remain 0.30–1.50 with output clamped to ReStim’s 0–1 input interval.
- Position Bias is preserved during relative Stroke Range changes.
- Uses the existing 0.20 s modifier transition.
- Intended for natural commands such as “reduce the stroke a bit” without asking the Director/LLM to invent numeric modifier values.
