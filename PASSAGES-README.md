# Vector passage candidate 2 — ceiling sequences and Dynamic conducting

## Start here

The complete local installation is:
`C:\AI\GwendolynModelLab\experiments\Vector88-Passages-Candidate2`

Close the previous Vector, open this folder in File Explorer, and double-click `start-vector1a.bat` there. Keep it with `standalone_entry.py`, `vector1a` and `dependencies`; a downloaded launcher by itself cannot work. The candidate starts stopped. Connect/start the normal input and ReStim output and press START / RESUME.

Open **Presets & tools > Semantic profiles > Passages / generated motion...**. This now opens the ceiling-relative sequencer. The previous attenuation/generator workbench is available through the advanced button.

## Primary timing variation — live A/B experiment

The Motion panel now includes **Primary timing variation (experimental)**, off by default, a style selector and Amount (0–1), default 0.65. For comparison, leave Preserve stroke range off, use a generated main L0 script, Mode 2 and the existing 3-second look-ahead, then switch timing variation on. No Gwendolyn restart is needed; restart Vector to load this code.

**Stroke groups** repeats an eight-detected-stroke pattern: regular, accelerate, accelerate, regular, decelerate, decelerate, endpoint dwell/catch-up, regular. Individual styles can be selected instead. This is deterministic grouping of source strokes, not recognition of authored phrases or musical beats. Each stroke retains its original start/end times and bounds; timing is reshaped within it. The dwell occupies the beginning of the stroke and the remaining motion catches up before the original endpoint. The style and amount are latched at stroke boundaries; on/off strength changes by at most 0.2 per complete stroke. Allow several strokes for the comparison to settle.

**Group multiplier** is an editable whole number from 1 to 32, default 1, saved with settings. Use the arrows, or type a number and press Enter or leave the field. It repeats each entry of the existing eight-entry pattern N times: x2 gives regular x2, accelerate x4 (two adjacent accelerate entries), regular x2, decelerate x4, dwell x2, regular x2. x3 triples the original entries, and so on. A complete cycle is 8 x N strokes. This changes grouping only; stroke durations, overall playback timing and the on/off blend rate stay the same. It applies only to Stroke groups, and changes take effect at the next eligible stroke boundary.

The transformed local speed is passed through Vector's existing primary pulse-frequency and pulse-width formulas and response curves, with their configured min/max limits. Primary alpha/beta geometry follows the reshaped stroke. Volume, carrier frequency, pulse rise time and the secondary/prostate pulse commands are retained. The main L0 and four-phase spatial path are retained; the primary pulse changes can still affect whichever primary hardware consumes those commands. This is intended for the current primary three-phase test. There is no automatic volume compensation.

The live line shows **ACTIVE**, **regular stroke**, or **Waiting / increase look-ahead**, plus baseline → modified generated pulse-frequency/width values in normalized units. The values are before authored-axis overrides, Director events and final output routing; enabled authored channels or events can supersede them. The existing pulse-section readouts also reflect generated timing output. Check that pulse-frequency/width sending is enabled, and use generated output rather than authored A/B/P0/P1 passthrough for the comparison.

The look-ahead buffer must contain a completed stroke before the beginning of that stroke reaches output. Incomplete strokes pass through unchanged; a stroke is never retimed halfway through because its reversal arrived late. If the source has slow strokes, increase look-ahead as needed. Output packet due-times are never shifted, so media alignment and overall duration are preserved. Off returns to baseline over up to five completed strokes (four at the default Amount). This experiment does not add strokes, delete strokes or change long-term tempo.

Offline verification: endpoint/monotonic warp tests, fixed-update input replay through the real queue, unchanged timestamp/volume/secondary checks, insufficient-look-ahead bypass and on/off recovery. A 500-frame ten-second replay produced 300 modified frames with max normalized pulse-frequency difference 0.171 and pulse-width difference 0.119, and zero due-time difference. These are software measurements, not a guarantee of perceptibility on hardware.

## Stroke range control details

The Motion panel has **Preserve stroke range (experimental; Modes 1-3)**, off by default. It contracts the generated primary alpha/beta path in proportion to the detected L0 stroke span, with a minimum scale of 10%. Full strokes keep their original geometry. On/off and changing spans slew over up to two seconds. Mode 4 bypasses this option because it already follows stroke amplitude. It does not regenerate the main funscript or reproduce Forge's complete pipeline.

For a useful comparison, play the same generated main L0 funscript in **Mode 2**, then switch the checkbox on/off without changing the other controls. Watch the live **spatial scale** readback. Allow two seconds for the blend plus time to hear/feel the passage. Compare the same section by seeking back. There is no automatic intensity compensation, so perceived strength may differ even though volume commands are unchanged.

The main L0 script must reach Vector through the normal input. Authored alpha/beta passthrough overrides generated geometry, so this option will not change authored A/B tracks. It does not alter four-phase E1–E4 output, secondary/prostate output, timing, pulse channels, pressure controls or narrative envelopes. Completed reversals repair stroke bounds in the look-ahead buffer; when an endpoint is not yet known, the most recently completed stroke is used. With no known stroke, the output stays unscaled. This is a live estimate, not perfect access to all original keyframes.

The toggle persists in settings. The desktop Vector shortcut points to this updated installation; close/reopen Vector to load the code. No Gwendolyn restart is required for this checkbox.

## Ceiling-relative preset details

Primary three-phase motion speech names: Mode 1 = Circular 0-180; Mode 2 = Top-Left to Bottom-Right 0-90; Mode 3 = Top-Right to Bottom-Left 0-270; Mode 4 = ReStim Original 0-360. Say "Switch to mode four" or "Set motion mode to two". Numbered names appear in both motion selectors. Saved settings and API values retain their original names. Restart Vector and Gwendolyn after updating.

The Primary ceiling is captured as the baseline when Apply is pressed. With a primary ceiling of 85%:

- Build & release: 85% -> chosen Peak (default 100%) -> 85%.
- Tease & return: 85% -> chosen Low (default 65% of baseline, approximately 55%) -> 85%.

These contour the primary volume while preserving its existing speed response and other modulation. They are not constant-volume scripts: a quiet/rest portion can still produce lower composed output. The live contour scales the composed primary volume, including authored V0 and events, with a final normalized 100% clamp. Secondary output is unchanged. Existing pressure attenuation still runs afterward. These are control values, not measured physical intensity.

This explicitly permits a build above the baseline Primary ceiling up to normalized 100%. Baseline is the return level, not the temporary maximum. Manual settings remain under operator control; changing them during a sequence changes the resulting output, so leave the baseline control steady while assessing the contour.

Add either preset to the list, reorder or remove steps, Preview, then Apply sequence. The initial editable example is Tease -> Build -> Build -> Tease. Each step has its own out/hold/return durations and destination. Each returns to baseline before the next begins. Hold freezes the live level and progression; Resume continues; Return to baseline removes the contour smoothly. Stop clears it. The final sequence level is baseline rather than a latched low value.

Up to 16 steps; each outbound and return leg 2–180 seconds; hold 0–120 seconds; whole sequence at most 30 minutes. Floors/destinations are normalized 0–100%. A zero primary ceiling cannot seed a sequence. At a 100% baseline a build has no further headroom.

Elapsed clock does not follow movie pauses. Media clock follows a fresh authoritative MPC/VLC clock, freezes when paused/unavailable, and holds after a seek/media change until explicit Resume. No sequence is armed automatically on startup.

## Motion-mode variety

The sequencer includes primary three-phase alpha/beta geometry selection: Circular, Top-Left -> Bottom-Right, Top-Right -> Bottom-Left, and ReStim Original. Mode changes preserve volume/response settings and the existing output FIFO. Previously queued samples finish first, then alpha/beta blend for two seconds. This avoids a fresh look-ahead buffer gap.

These modes affect three-phase alpha/beta; four-phase E1–E4 retain their separate spatial model. Equal volume values do not guarantee equal perceived strength. Pulse-rate generation can also depend on spatial position. This is spatial contrast, not an intensity-matching claim.

## Script awareness

Use **Load / sync authored funscript timeline...** in the sequencer (also Session > Director > Funscript timeline...). Load the actual script being played, especially if Forge generated a separately named file. Choose Auto media player or MPC/VLC direct, and confirm the current player position is synchronized. Manual preview and inferred pattern sync are not authoritative timing for the Dynamic conductor's predictions.

Gwendolyn receives current script activity and the next 10/30 seconds, plus live signal/queued-output context. Scores describe relative authored motion, not felt electrical intensity. A loaded but unaligned, paused or stale-clock script causes Dynamic conducting to wait rather than invent a forecast.

## Gwendolyn Dynamic conductor

Restart the normal Vector + Omni Gwendolyn session after starting candidate 2. The session hooks were updated in Model Lab; the original external Gwendolyn source/config was not changed. `backup-passage-candidate2/gwendolyn_entry.py` contains the previous entry.

The new Dynamic Vector conductor panel defaults to a 45-second review interval, adjustable to 30/45/60/90/120 seconds. It is enabled as a capability, but **autonomy still must be armed**. Say `Start autonomous session` while Vector is running. This preserves the current authored input rather than replacing it with generated motion. End the separate autonomous modulation mode before arming full conducting.

During an armed session the Director chooses one sequence, three-phase motion mode, captured texture or variation, or a reasoned wait. Decisions use the narrative arc, recent changes and current/upcoming script activity. Reviews have their own schedule, independent of the 15-second conversation-idle gate, and do not stop at the older two-to-three-intervention target. Recording, active processing, holds, closure and the shared inference lock still take priority. An active sequence is allowed to finish; reviews do not repeatedly replace it. The cadence is a review interval, not a guarantee of a physical change every 45 seconds.

The status line shows the latest decision/wait reason. Changes are readback-verified before narration. The controller does not infer the user's feelings or game compliance from motion scores. Narration tracks actual passage phase/readback. A conducting hold/disarm also holds the active passage; resuming conducting reanchors/resumes a held passage. Existing explicit session Stop uses the existing immediate stop path.

Commands:
- `Start passage` or `Start build and release`.
- `Start passage build 90 seconds hold 30 seconds release 60 seconds`.
- `Start tease and return`.
- `Start red light green light sequence`.
- `Hold passage`, `Resume passage`, `Restore passage`.
- `Set motion mode to ReStim Original`.
- `Set motion mode to Top Left Bottom Right`.
- `Start autonomous session`, `Hold autonomous session`, `Resume conducting`, `Stop conducting`.

Existing source-preserving autonomy, Signal Lab and conversation-only mode retain their own restrictions. Dynamic conducting does not itself arm/resume physical output. No GPU model was added. A review normally uses one decision inference and, after a verified change, the existing narration inference. More frequent reviews therefore use more of the existing model's time.

## API and compatibility

New loopback endpoints: POST `/v1/passage/sequence`, `/v1/passage/sequence-preview`, and `/v1/motion-mode`. State reports sequence step, phase, captured baseline, live nominal ceiling, and requested/applied motion mode. Mode acceptance is a queued request, not immediate evidence that the delayed output has changed. Capabilities advertise the new features. The legacy attenuation endpoints remain available for backwards compatibility.

The archive contains Vector source/dependencies/tests and the Gwendolyn session hook files. The private local calibration/profile copy is omitted from the archive. Keep the installed folder for your current calibration. Candidate 1 and your previous Vector releases remain separate.

## Verification and limits

Offline checks cover the 85->100->85 contour, tease/return, sequence boundaries, amplified-factor restoration, invalid values, queue preservation, smooth geometry transitions, API handling, clock freshness, authored/event/pressure volume routing, explicit/armed authority, holds, malformed model responses, readback receipts, and the review-to-execute-to-narrate path with model/device boundaries mocked. Existing generated-motion and output-composer baselines remain checked. The installed Gwendolyn wrapper stack and immediate Stop success/failure paths loaded and passed offline verification. The sequencer opened in a Python 3.13 UI smoke test.

Live model latency, device playback and subjective intensity matching remain untested here; localhost sockets are blocked in this execution environment. The model may defer or return an invalid decision, which is logged/shown and does not authorize a fallback physical change. The Dynamic conductor does not promise a change at every review.

## Spoken command repair (10 November 2026)

Polite commands such as “Can you start the red light green light sequence?” now take the deterministic sequence route, including the article and question mark. Sequence requests expose only sequence/state tools, and execution rejects substitution with motion mode or another control family. Verified sequence/mode receipts bypass creative prose filtering only when their exact readback-grounded confirmation is being spoken. Dynamic decision requests now explicitly request a JSON object with a separate token budget and lower temperature; ordinary conversational requests retain their own settings. Restart Gwendolyn to load the repair; Vector itself does not need restarting for this change.

## Approval repair (10 November 2026)

Punctuated short affirmatives such as “Yes, please.” now bind to a single recent published semantic proposal when its parsed action matches the stored pending action. The exact report of proposing Rough texture was reproduced against the installed parser/wrapper stack. Stale/displaced offers, multi-action offers and qualified/negative replies remain rejected. Action-shaped Vector JSON is never spoken as evidence of execution; only a verified controller receipt may confirm a change. Restart Gwendolyn to load this session-hook repair.

## Capability speech repair (10 November 2026)

The primary-only profile restriction catalogue is no longer used as a spoken fallback for unsolicited unavailable-control offers. Unsupported offers and their pending action are removed while useful narrative sentences remain. If a reactive answer contains nothing else, one no-tool conversation repair is allowed; a second invalid offer is suppressed. Direct requests for an unavailable action receive a short specific explanation. Execution restrictions remain enforced. Primary-only guidance now distinguishes the newly supported three-phase motion modes and ceiling sequences from unavailable four-phase/anatomical focus controls. Restart Gwendolyn to load this voice-runtime repair.

## Conversational acknowledgement repair (10 November 2026)

Brief acknowledgements such as “Sounds good” now use a compact conversational context instead of the full controller prompt. Previous diagnostic recovery lines are excluded from that context. This path has no tool authority and cannot replay tool calls. If a reply still falls into repetition recovery, it gives a brief acknowledgement without making a claim about physical output. “Sounds good” can approve one recent, explicit, matching stored proposal; otherwise it remains ordinary conversation. Exact action approvals and direct controls retain their normal execution/readback paths. Restart Gwendolyn to load the repair.

## Timed sequence completion repair (10 November 2026)

A completed retained plan is now reported as completed=true, active=false, with zero remaining time. Completed plans remain available to the local controller for terminal-level handling, but Gwendolyn receives their label only under last_completed (past context), never as a currently running game. The Gwendolyn adapter also corrects older Vector readback that said active=true with phase=complete, so restarting Gwendolyn alone applies the narrative repair to an already running candidate. The new Vector code additionally reports the lifecycle flags directly when next restarted.

A running Red light / green light sequence now exposes an explicit game_phase: tease_return=red_light, build_release=green_light, and completion=None. Older readback is mapped from the current preset. Default steps last 30+10+30 seconds each, so the four-step example ends after 280 seconds (4m40s), returning to the captured primary ceiling. The broader session continues, but the finished timed game is not automatically restarted.
