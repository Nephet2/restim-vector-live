# Vector 1A 1.6.0-alpha56

Alpha56 turns anatomical Spatial Focus into real signal transforms rather than captured profile labels.

## Top focus transform

- E1 = glans, E2 = shaft, E3 = lower shaft, E4 = root.
- Default nominal electrode excursion ceiling: **0.85**, leaving headroom below the T-code hard limit.
- Focus gain is applied around ReStim neutral (0.5), so neutral remains neutral.
- Default full-strength weight envelopes:
  - Glans: 1.10 / 1.00 / 0.90 / 0.80
  - Shaft: 1.00 / 1.10 / 1.00 / 0.90
  - Lower shaft: 0.90 / 1.00 / 1.10 / 1.00
  - Root: 0.80 / 0.90 / 1.00 / 1.10
- Top Sweep moves the weighting peak continuously through E1-E4 with motion position.
- Transform is applied after authored-vs-generated source selection and before the final 0..1 clamp. Authored E1-E4 axes therefore receive the same bounded focus treatment.

## Bottom focus transform

Secondary Alpha is remapped into an anatomical excursion window:

- Prostate Focus: 0.50..1.00
- Anal Focus: 0.25..0.75
- Perineum Focus: 0.00..0.50
- Bottom Full / Sweep: 0.00..1.00

A Bottom Focus Strength control fades continuously between the ordinary full Alpha range and the selected focus window.

## Director

The existing `top-focus` and `bottom-focus` Director endpoints remain compatible with the SillyTavern v0.8 / Ollama bridge v2.9 tool chain, but focus labels no longer need to be captured first. `/v1/state` now reports active focus weights, headroom, strength, and the bottom Alpha window.

## Validation

129 automated tests pass, including new headroom, neutral preservation, moving top sweep, and prostate-window tests.
