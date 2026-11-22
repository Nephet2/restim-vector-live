# Handy interface

Launch the existing desktop Vector shortcut, then Session → Handy Interface. Fully close/reopen Vector once after source updates. After that, mode changes and script-library changes can resume automatically without restarting Vector or pressing Start again. An explicit operator pause cancels a pending handoff.

## Connection

Put Handy in Wi-Fi Online mode. Enter the short device key in Connection key and the Application Key alone in Application key / token. Do not concatenate the Application ID and Key. An account sign-in token is a different credential. Credentials are stored only if Remember keys is selected, using Windows current-user DPAPI. They are excluded from the patch ZIP.

Application keys use API v3. Client API tokens can negotiate Bearer authentication on a read-only connected probe after a 401; motion requests are never replayed for negotiation. Connection-key-only API v2 permits native Manual; timed firmware-4 playback requires API v3.

## Controls

- Follow Funscript: uses the loaded Vector script and an authoritative MPC / HereSphere clock. MFP may continue supplying other Vector outputs, but L0 pattern matching alone is not used to position Handy: repeated passages can produce incorrect clock jumps. Load the corresponding script and use MPC clock or direct player input. Source loss pauses physical output.
- Script Library: import/open funscripts, five original starter patterns, or reuse saved VacuGlide speed tracks converted into strokes. Loop, timeline seek, and pause/resume are available. Seek pauses. VacuGlide valve events are not reproduced by Handy.
- Manual defaults to Native continuous Manual on both APIs: the motor alternates on Handy itself at a native speed percentage and within the selected range. No periodic position refill controls those strokes. Tempo multiplies speed, capped at 100%. Zero speed or collapsed range stops motion. The native API supplies no phase clock, so no fictional live position is drawn. The timed chart now samples the locally evaluated trajectory at 50 Hz while the display refreshes at 10 Hz; its former 10 Hz history could make fast smooth strokes look angular.
- Untick Native continuous Manual for timed API-v3 strokes with a cycles/second slider and optional Gradient reversals. The graph and range marker show commanded targets, not measured position. The Native motor checkbox applies only to Manual; it does not change script playback to HAMP.
- One range slider has minimum/maximum handles. Drag either handle; arrows nudge the selected handle, Space selects the other. A gold marker shows the current timed target when available.
- Continuous tempo: 0.25–2× with 0.25, 0.5, 1 and 2× presets. In Follow mode, 1× preserves video timing; other tempos rescale script time until seek/resume.
- Invert script: reverses the authored axis before applying range limits.
- Offset: −10 to +10 seconds in 50 ms steps; positive samples ahead (leads), negative samples earlier (delays). Applies to script and Follow, not native motor speed. Press Enter after typing. Pausing/source loss is immediate locally and does not extend playback by the offset.
- Gradient: library files use the same monotone Hermite tangent calculation as Vector's Signal Lab-derived timeline implementation, retaining authored endpoints and holds without overshoot. Follow explicitly requests the Gradient timeline sampler. Timed Manual uses cosine strokes with zero velocity at reversals. Native Manual keeps the device's native motor profile; Gradient does not modify that firmware profile.

## Timing and limitations

Captured hardware diagnostics show approximately 0.9 s per cloud request. Live changes and remote stop therefore remain subject to cloud latency. Native Manual avoids streamed stroke timing, but its actual slow-speed behaviour still needs operator retest. Changing native speed alone does not resend the range or restart the motor. Unchanged settings are checked every five seconds.

Timed playback prepares HSP before generating points. The finite horizon adapts to RTT and uses the device-reported point capacity (the captured device reports max_points=9545), with at most 90 points per request. Linear playback sends authored event times directly. Gradient curves are subdivided adaptively at half a percentage-point interpolation error before integer encoding. Buffers share an exact endpoint, without advancing past it by a sampling interval. Fast curves that require several requests are prefilled before play; their trajectory is projected to the expected completion time and played against the same server clock. Source loss or Pause cancels prefill before any late play. Request throughput and physical motor limits still bound achievable speed. Edits flush/replace the plan after an in-flight request; the ordinary refill delay is bypassed. HSP stop is one direct request when mode is known. Diagnostics include the last HSP state to distinguish starving, stopped, and acknowledged running states.

The operator still reported mid-stroke stops after sparse point reduction, especially on slow strokes. Sparse encoding alone did not resolve the physical symptom. Native Manual is now the default alternative; Gradient addresses reversal acceleration in timed motion. Neither change is claimed as a physically verified cure. Full device testing remains with the operator. Scripts are sampled locally; their complete files are not hosted/uploaded. Targets and commands travel through Handy's HTTPS cloud.

## Validation

60 Handy offline checks cover playback, bounds, protocol encoding, credentials, simulated 900 ms RTT, cancellation, Gradient endpoint slopes, inversion/offset, mode handoff and operator cancellation, native API-v3 operation without HSP refills, shallow trajectory reconstruction, and real Tk construction/range controls. Existing navigation, input pipeline and connection status checks are also run. An offline visual preview was inspected for the combined range marker and smooth timed trajectory; it never connected to hardware.

Vector STOP includes Handy. Closing its window pauses output. Native motor movement persists between commands; an unconfirmed remote stop is reported.

## Next stage and recovery

See OUTPUT-CONTROLS-DESIGN.md for the planned linked Handy/VacuGlide intensity panel. VacuGlide runtime behaviour is unchanged by this update. The ZIP is a source patch for this existing Vector88 folder, not a standalone program. The desktop shortcut's source is updated locally. Earlier source checkpoints are under backups, and the patch ZIP is versioned separately.

## Device stroke window and streaming regression update

The operator confirmed Native Manual is substantially smoother, while unchecked timed Manual still stops/starts. They independently observed a 0–56% global device stroke window in Handyverse and confirmed that resetting it to 0–100% restored the expected physical span. The vendor has both a global slider/stroke limit and HAMP's range within that window. Vector now reads and displays the global window on connection and shows the effective requested physical range. Read device limits refreshes it while stopped. Set device 0–100% is an explicit stopped-only action, with readback; connection does not widen an existing device limit. Other applications may change the limit, so read it again after using Handyverse.

A concrete defect was found in timed refill: advancing stream_end beyond the last queued endpoint by one sampling interval could omit a reversal in that gap. It is removed. Event-based linear planning, adaptive Gradient points, reported buffer capacity and multi-batch startup prefill replace the fixed-grid/one-batch assumption. Tests retain a 10 ms reversal inside the former gap and sustain a full-range 3 cycles/s Gradient trajectory with simulated 900 ms per-request delivery. Bulk prefill cancellation is tested. These are offline protocol checks; the operator still needs to verify physical smoothness and remaining low-speed limitations.

## Follow clock jitter update

The operator supplied Gradient and Linear target traces and confirmed they were from Follow Funscript. The Gradient trace contains abrupt extra reversals. These are commanded-target charts, so they alone do not establish physical device movement. Code review found that small corrections from nominally precise player clocks were being applied directly to script phase, including backward corrections.

Follow now advances using monotonic elapsed time and gradually slews ordinary precise-clock corrections at up to 5% of source speed, with a 20 ms deadband. Seek detection compares a measurement with the predicted clock, rather than comparing two noisy measurements. Large discontinuities and source changes retain immediate stop/reinitialisation. Coarse whole-second clocks retain elapsed-time advancement. Playback rate changes revise the timed plan. Chart history timestamps are strictly increasing, and old traces are cleared on discontinuities without inventing pre-seek history. Diagnostics include raw clock, smoothed clock and last correction error.

New regressions alternate source timestamp errors up to ±400 ms and assert monotonic bounded-speed phase and chart targets, and verify that an actual seek resets immediately with one new history point. All 57 Handy checks and the standalone startup/shutdown smoke test pass. The live player feed and physical movement still require operator retest.

## Gradient live-edit update

The operator reports that both interpolation modes are much smoother except at very slow speed; Gradient seems to add latency and pauses during live range changes. The code allowed the multi-batch startup prefill path to run on revisions of an already playing stream, flushing the old motion before several request round trips. That live-edit path is removed. Initial startup retains prefill, but active edits use one hsp/play request containing the replacement points.

For dense curves, the edit approximation increases only as needed from 0.5% to at most 2% positional interpolation tolerance before integer wire rounding, to retain two request round trips plus 0.5 s of queued motion within 90 points. Authored event times and endpoints remain. Ordinary refills return to the normal curve tolerance. The last edit tolerance is exposed in diagnostics. Extremely dense authored scripts can still exceed request throughput; this update does not promise instant cloud control.

The fast Gradient simulation now includes two range edits at 900 ms/request and verifies motion remains queued, with atomic replacement commands. A separate regression asserts one request for a fast dense live edit and sufficient replacement time coverage. All 58 Handy checks pass, and the startup/shutdown smoke check passes. The operator must still verify physical behaviour. Very slow stop/start remains unclassified: Native Manual at similarly slow physical motion can help separate transport timing from device regulation/friction; no minimum speed has been imposed to conceal the symptom.

## Prepared-session restart update

The operator compared against Handyverse's synchronization test and observed effectively instant Stop/Start. Its screenshot shows a script already set. The browser-only page could not be inspected as readable source, so Vector does not claim to reproduce Handyverse's implementation. The previous explanation described Vector's buffering choices, not an unavoidable device delay.

Vector formerly discarded its prepared-session flag on every start and repeated mode/setup and potentially multi-batch prefill. A confirmed HSP stop now preserves that prepared state. Restart on the same known HSP connection sends one atomic replacement-and-play command, using the same bounded edit planning as live range changes. It generates fresh targets and a fresh server-clock anchor rather than replaying stale queued motion after a long pause. New connections, command failures, or a switch to native HAMP invalidate this reuse. First-time setup/preparation remains separate. Reconnect Vector after using Handyverse or another controller, since an external controller may change the device's mode or session.

New regressions verify one play request with no mode/setup/prefill on a dense warm restart, and verify HAMP mode forces proper timed setup. All 60 Handy checks pass; the startup/shutdown smoke check passes. Physical warm-restart latency has not yet been measured after this change, and no claim of parity with Handyverse is made.
