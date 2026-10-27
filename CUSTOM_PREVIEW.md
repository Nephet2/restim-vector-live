# Vector 1A — Custom Curves preview 2 (alpha82 base)

## Changes
- Fixes repeated UI freezes when a ReStim port is incorrect, unavailable or timing out. Health telemetry no longer waits for the socket I/O lock.
- Connect and Disconnect buttons use per-endpoint background workers; the newest pending request replaces older pending requests.
- Automatic ready startup leaves ongoing retries to the existing reconnect monitor. Session startup completes WebSocket handshakes off the UI thread before reporting READY.
- Rejects late connection requests after the client is closed.
- Places Edit Custom curves immediately beside the Spatial model dropdown.
- Retains four editable E1-E4 curves, presets, straight/smooth interpolation, live editing, 3D preview, named profiles/descriptions and semantic API discovery/selection.

MFP stream replacement, WebSocket framing/keepalive, independent output lanes, stale-frame rejection, Stop behaviour and recovery-neutral output logic are retained. Read-only health fields are best-effort snapshots and can straddle a connection transition.

## Run the normal application
Extract the entire source ZIP into a new writable folder and double-click **start-vector1a.bat**. This starts the full standalone source application with normal connection and motion-output support. No AI model, Gwendolyn service or GPU is required. Python 3.11+ is required; Python 3.13 x64 is recommended for the included, hash-verified Pillow 12.0.0 dependency. The normal launcher loads the included dependency only on its compatible runtime. Other runtimes may install optional Pillow using `python -m pip install ".[preview]"`. Civet Bluetooth support uses the pinned Bleak dependency installed by that command.

No personal settings are shipped. To retain preferences, close Vector and copy your existing `profile/Vector1A/settings.json` into the matching location in the new folder. Keep the old installation intact. Otherwise configure the correct ReStim port in the new copy; generic defaults do not know your local port.

**START_CONNECTION_TEST.bat** permits ReStim handshakes but blocks motion/axis output, for testing connection responsiveness. **START_UI_PREVIEW.bat** blocks all connections for UI-only trials. Use these special launchers only for their stated tests; the normal application starts with **start-vector1a.bat**.

## Validation
The user reproduced freezes by entering an incorrect ReStim port and confirmed smooth window movement with the corrected test copy and ReStim unavailable. A controlled simulated 700 ms timeout stalled the old UI heartbeat by 676 ms; the fixed version measured 9 ms after startup paint. This is a UI responsiveness test, not a new physical-hardware test.

251 local tests passed; 34 real-network tests were blocked by the restricted execution environment. Windows CI runs the full suite on Python 3.11, 3.13 and 3.14 before publication. Added checks cover nonblocking health reads and Connect, caller-thread Tk reads, newest pending requests, Disconnect, pending-command cancellation, closed-client rejection and startup handshake placement. Actual Tk geometry confirms the button sits 8 pixels beside the dropdown.

This distribution is a **Python source preview**, not a portable executable. Earlier alpha84/85 Bearfoos detections remain unresolved and have not been declared false positives. No quarantined files are restored and no new EXE is built. Any clean scan applies only to the specific source package scanned; it is not a safety determination for the old executables.
