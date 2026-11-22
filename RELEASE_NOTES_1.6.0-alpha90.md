# Vector 1A v90

Builds on v89 (tuned response defaults) and the v88 passage candidate, including the **Signal Quality** diagnostics panel.

## Rest behaviour (Volume response panel)
- **Rest after (s):** how long input may stop before V0, C0, P0, P1 and Prostate V0 drop to their rest levels. Longer values ride through script holds. Default 0.25 s (unchanged behaviour).
- **Fall time (s):** V0 and Prostate V0 ease down to rest on an S-curve instead of stepping. If motion resumes mid-fall, V0's return ramp continues from the level reached. Default 0 (instant step, as before).
- **Reversal window (s):** input only counts as active if L0 changed direction recently, ignoring moves under 1% and moves that start after L0 has stopped. Keeps parking moves such as MultiFunPlayer auto-home after a pause from raising volume. Default 0 (off).
- Tested values: Rest after 1.0–1.5 s, Reversal window 1.0–1.5 s, Fall time 1.0–2.0 s. Keep the Reversal window at least as long as your longest script hold.

## Output envelopes (off by default)
- Per-axis envelopes for V0, C0, P0, P3 and P1: separate attack and release, a jerk limit, and look-ahead advance to cancel the added delay. V0's controls are in the Motion section; the others are under each pulse section's composed command. A status line shows the advance, when the look-ahead is too short, when an envelope replaces pulse smoothing or timing, and when Howl pulse supplies P0/P1.
- `tools/envelope_eval.py` evaluates envelope settings offline against the engine (no device or network).

## Safety fixes
- **Base volume 0** now mutes generated Primary and Prostate V0 immediately. Previously, samples already queued could send Primary V0 at 100% for the look-ahead (longer if the value was typed without being applied).
- **Lowering Base volume** no longer clamps queued Primary V0 to 100%; Prostate follows the new Base volume at once.
- **Neutral** now rejects live frames calculated before it, as Stop already did.
- **Resume** no longer starts output when settings fail validation.
- **Tempo:** a brief loss of the media position during a tempo change holds the warped position instead of jumping to the raw script position.

## Installation

Extract the Windows source ZIP into a new folder and run `start-vector1a.bat` with Python 3.13 x64 installed. Keep the bundled dependencies beside the launcher. To migrate preferences, close both copies of Vector and copy your previous `profile/Vector1A/settings.json` into the corresponding folder in the new installation. The new settings start at their defaults (off) until you change them.

This alpha prerelease includes a SHA-256 checksum for the Windows source ZIP.
