# Custom curves source preview (alpha82 base)

## Included
- Four independently editable E1-E4 curves, presets, straight/smooth interpolation, live editing and 3D preview.
- Named profiles with editable descriptions; semantic API discovery and selection.
- Idle editor redraws are skipped until visible state changes.
- Alpha82 network modules are unchanged, retaining stream replacement, ReStim keepalive, callback deferral and fixed connection-panel layout.

## Start
Use Python 3.11 or newer. The manually attached Windows source ZIP includes hash-verified Pillow 12.0.0 files for Python 3.13 x64; other Python versions can install their compatible Pillow with `python -m pip install ".[preview]"` after removing the incompatible dependencies folder. A plain GitHub source checkout can also use that install command for optional smoothing.

Extract into a new writable folder and run START_UI_PREVIEW.bat first. It blocks socket connections/binds, Bluetooth connection initiation, controller startup and external app launching. It suppresses automatic connections and media polling. No personal settings are included. Settings created in this folder are independent of other installations.

The ordinary start-vector1a.bat starts the full source application with connection support. This preview has not completed a new end-to-end hardware test. Do not overwrite a working installation. Copy settings only deliberately and retain your backup.

## Validation and limitations
245 local tests passed; 34 network-dependent checks were blocked by WinError 10013 in the restricted test environment. A dedicated idle-redraw regression is included. The tester reported that the disconnected UI preview works well. GitHub's Windows CI is intended to run the full suite independently.

Defender reported no threats in the local source preview folder. Seven prior build-tool packages (1,605 non-metadata files) matched freshly downloaded wheels whose hashes matched PyPI metadata. The earlier alpha84/85 Bearfoos detections remain unresolved; a source scan and successful startup do not establish the safety of those executables. No quarantined files were restored, protections changed or new executable built for this draft. Further runtime dependency review and a credible disposition of those detections are required before executable publication.

The alpha83 closed-editor responsiveness issue was not reproduced as a sustained source-level regression in short controlled trials. Idle five-canvas redraw work was reduced, but an executable/environment-specific issue remains possible.

## Package contents
Personal profiles, addresses, settings backups, logs, local paths, quarantined builds, caches and build environments are excluded. Existing licences and credits are retained. Vector remains standalone; no AI model or Gwendolyn service is required.
