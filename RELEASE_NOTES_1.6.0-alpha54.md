# Vector 1A 1.6.0-alpha54

## Director awareness
- Adds captured semantic Area of Effect profiles: Narrow, Focused, Medium, Broad, Full.
- Adds `/v1/semantic/area-of-effect`.
- `/v1/state` now includes a read-only `future` summary derived from Vector's already-calculated deterministic queue: direction, speed trend, projected speed, next reversal timing, and endpoint approach.
- Adds stroke progress and reversal distance to Director motion state.
- No AI dependency and no change to signal-generation cadence or queue authority.
