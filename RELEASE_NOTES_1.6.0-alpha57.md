# Vector 1A 1.6.0-alpha57

## Stronger anatomical focus commissioning

- Default Top nominal headroom reduced from **0.85** to **0.65**.
- Top focus envelope increased to **1.30 / 1.05 / 0.80 / 0.60** from focused to farthest region.
- Shaft, lower-shaft and root profiles move the same stronger envelope to their corresponding E-axis location.
- Top Sweep now moves that stronger envelope continuously across E1-E4.
- Top focus strength range increased from **0-100%** to **0-175%**.
- Strength still blends around multiplier 1.0, so 0% means no anatomical weighting.
- At the default 0.65 headroom, 175% peak strength reaches about **0.9956** at a full positive excursion, remaining below the T-code hard ceiling.
- Bottom Alpha focus behaviour is unchanged from Alpha56.
