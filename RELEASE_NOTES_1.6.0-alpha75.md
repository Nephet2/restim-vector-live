# Vector 1A 1.6.0-alpha75

## Continuous autonomous motion

- Fixes generated L0 flattening when a motion plan reaches its review horizon before Gwendolyn supplies the next plan.
- `duration_seconds` now marks a plan as due for review; it does not stop or hold motion.
- The current deterministic pattern continues until replaced, explicitly held, returned to authored T-code, or stopped.
- `/v1/state` reports `motion_source.review_due` when the horizon has passed.

This preserves continuity through slow or failed model decisions while leaving explicit hold, authored-source return, and Stop authoritative.
