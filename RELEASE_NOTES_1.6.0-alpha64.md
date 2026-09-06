# Vector 1A 1.6.0-alpha64

## Full-funscript timeline visibility — first commissioning build

- Adds a read-only `.funscript` timeline loader. The authored script is never used to drive output in alpha64.
- Adds **MFP pattern sync**: recent incoming L0 is matched against the loaded funscript to estimate current script/media position while MFP remains the normal live source.
- Adds **Manual preview** clock with seek/play/pause for commissioning without media playback.
- Adds deterministic authored-script summaries for **now (~1 s)**, **next 10 s**, and **next 30 s** including range/amplitude, focus region, speed, reversals, relative energy band, and 30-second build/ease trend.
- `/v1/state` now exposes the `timeline` object; `/v1/capabilities` describes timeline availability and supported clock sources.
- Adds a **Funscript timeline...** window to the Director API UI for loading a script, choosing clock source, and observing sync/lookahead status.
- Existing MFP input, Vector signal generation, ReStim routing, stop/resume latch, and short deterministic output queue forecast are unchanged.

### Important commissioning limitation

Pattern sync is an estimator, not a media-player clock. Repetitive funscripts may have ambiguous regions and large seeks may require reacquisition. Alpha64 exposes sync confidence and Gwendolyn must not claim long-range future knowledge until the timeline reports `synced: true`.
