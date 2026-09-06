# Vector 1A 1.6.0-alpha76

This release brings the public alpha49 build up to date with development through
alpha75 and adds **MFP WebSocket input**. Vector remains a standalone Windows
application: no AI model, GPU, voice stack or cloud service is required.

## New in alpha76: MFP WebSocket input

In MFP, add a **WebSocket** output and set its URI to:

```text
ws://127.0.0.1:12345/ws
```

Start Vector's listener before connecting MFP. TCP and UDP remain available on
the same configured input port; `/tcode` and `/` are WebSocket path aliases.
Use one MFP output to Vector at a time. Disconnect the previous TCP/UDP output
when switching so that the same motion is not sent twice.

WebSocket feeds the existing T-code parser, authored-axis router and deterministic
queue. Your motion settings and commissioned MFP offset continue to apply.
For a new setup with Vector's default 2.00-second delay, begin at MFP **-2.00 s**.
The input status identifies **Receiving (WEBSOCKET)** when L0 arrives.

The listener handles text-message boundaries, fragmentation, ping/pong, close and
reconnection. Invalid frames and oversized messages are rejected before reaching
the signal engine. This is local `ws://` input; no TLS server or additional
runtime dependency has been introduced.

## Changes since alpha49

### ReStim connection resilience

- Primary and secondary ReStim now have independent output workers. A slow
  destination cannot block the other destination or the calculation engine.
- Only the latest pending output frame is retained; frames older than 250 ms
  are discarded. Recovery does not replay a delayed backlog.
- Reconnection sends a zero-volume neutral frame before fresh output resumes.
  Vector does not press ReStim's Start button.
- Per-output diagnostics report send age, cadence, dropped/stale frames,
  worker health and reconnection status.

### Spatial focus, gain and profiles

- Captured Texture and Variation profiles provide named, user-calibrated choices.
- Top and Bottom Spatial Focus controls apply bounded anatomical transforms;
  focus strength and Top headroom are adjustable.
- Independent Top/Bottom Spatial Gain controls provide stepped changes,
  configurable bounds, smooth ramps and Restore.
- Focus and gain history are available to optional Director companions.
  Electrode calibration remains in ReStim.

### Script awareness and modifiers

- Optional funscript timeline loading with summaries of the current pattern,
  upcoming 10/30-second windows and relative script energy.
- VLC/MPC media-clock support, automatic funscript discovery, MFP pattern-sync
  fallback and manual preview. Direct-clock polling, extrapolation, seek handling
  and stale-clock diagnostics include the later development fixes.
- Timeline observation alone does not drive output. Pattern matching remains an
  estimate and may be ambiguous for repetitive scripts.
- Stroke Range (0.30–1.50), Position Bias (±0.35), Curve Smoothing and smooth
  transitions can modify the authored motion.
- Temporary 0.5x/2x authored-tempo windows restore to the current authored motion.
  Accelerated tempo needs a loaded, synchronized timeline. Director-requested 2x
  windows are limited to 15 seconds for challenging/testing authored energy.

### Optional Director integration and generated motion

- A loopback-only API, disabled by default, exposes state, capabilities and
  bounded high-level controls for external companions such as Gwendolyn.
- Stop remains latched until explicit Resume, even while MFP continues sending.
  Resume clears stale queued output and returns the engine to Buffering.
- Read-only controller state supports companion push-to-talk interpretation.
- Optional motion plans select sine, triangle or breathing patterns; Vector
  validates the plan and generates L0 at a fixed cadence. Authored T-code is the
  default source, and the Director does not submit raw axis samples.
- Plan timing uses **125–3000 ms per one-way stroke**, with at least 0.10 travel
  inside the normalized 0–1 range.
- Alpha75's continuity fix is included: the plan duration marks a review horizon,
  not a motion stop. The current pattern continues through delayed Director
  decisions until replaced, held, returned to authored input, or stopped.
  State exposes `motion_source.review_due`.

## Upgrade

1. Close the older Vector instance and back up
   `%LOCALAPPDATA%\Vector1A\settings.json`.
2. Extract `Vector1A-1.6.0-alpha76-windows.zip` into a new folder.
3. Run `start-vector1a.bat` with Python 3.11 or newer installed.
4. Review saved connection, routing and startup settings. Existing TCP/UDP users
   can retain their current connection method.
5. Check motion in ReStim's graphical display with stimulation hardware disconnected.

The release folders share the same settings location. Retain the backup for
rollback. New options use their defaults when absent; existing saved options
(including Director enablement) are preserved. Gwendolyn is not bundled or required.

## Release verification

The full test command is now `python -m pytest -q`, covering both unittest
classes and standalone test functions that the previous CI command skipped.
GitHub CI checks Python 3.11, 3.13 and 3.14 on Windows.

New tests cover WebSocket framing and validation, all-axis delivery, TCP/UDP
equivalence, quiet connections, reconnect/restart, deterministic queue timing
and the Stop latch. An inherited generated-motion test now waits for actual
held samples instead of assuming an exact Windows scheduling interval.
