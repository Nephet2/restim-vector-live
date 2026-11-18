# Vector — Motion + intensity

This is the separate **Vector commissioning build**. Run `start-vector1a.bat` from its own folder and look for **Commissioning** in the title bar. Close the current Vector instance before starting this one because both can use the same input ports and devices. To return to the current build, close this one and launch your original shortcut. The portable ZIP starts with a fresh local profile.

## Session overview

Use **Use input** to apply the pending player choice. The active source, player clock and associated funscript are shown below it. **Load funscript** opens the local timeline when MultiFunPlayer is active and associates a script with the current video for MPC-HC, HereSphere or DeoVR.

For DeoVR, enable its Remote Control API, select **DeoVR**, enter the player device address and port **23554**, and click **Use input**. Start a video in DeoVR. Vector looks for matching scripts for local paths. For online video, use **Load funscript** to associate a local file with the current video.

Each output row shows its own connection or device status. ReStim rows report Vector's engine state and last socket write. Handy reports command acknowledgement; VacuGlide shows device-reported speed and verified stops. Click an output name to open its controls.

## Shared transport

Each column has a Link to shared transport checkbox, selected by default. Pause linked / Resume linked act on selected devices only. Checking a link never starts a device. Individual Pause and Resume remain available for each device. STOP ALL uses Vector’s existing global stop and includes unlinked devices and ReStim. Closing the shared panel pauses both Handy and VacuGlide. Linking coordinates Pause/Resume, not tempo, script choice or physical phase.

Existing connections are reused. Connection / settings opens the established Handy or VacuGlide interface for keys, connection and device limits. Shared Resume checks both selected devices before starting either. Per-device status shows requested versus confirmed state; errors are not an all-device success. A queued resume is cancelled by operator Pause, global STOP, shutdown or a changed VacuGlide stop revision.

## Handy — motion

Choose one checked source: Funscript follows the current Vector MPC-HC / HereSphere / DeoVR player clock and loaded funscript; Script plays the selected library file; Manual uses its speed control. Invert script acts before range mapping. One two-handle slider sets stroke range with a timed target marker; native motor mode has no invented phase marker. Tempo is continuous 0.25–2× with four presets. Native Manual exposes motor speed percentage; untick Native Manual for a timed cycles/second slider. Gradient remains available for timed motion. Offset is −10 to +10 seconds: positive leads, negative delays script sampling. Offsets do not change native motor speed. Global device stroke limits remain visible when known and are edited in Handy settings.

## VacuGlide — intensity

The top of the VacuGlide column shows its selected source. While paused, choose **Funscript**, **Script** or **Manual** in this column to select a mapped source independently of Handy. The VacuGlide Interface marks the same mapped source. Pause linked requests a VacuGlide stop for either interface when VacuGlide is linked. Resume uses the selected source, including the existing Script Editor modes. Select a mode in the Script Editor to switch to that mode explicitly. Trim is the maximum mapped intensity and respects the existing Director range and device speed cap. Manual uses the trim directly. The separate offset is −10 to +10 seconds, positive leads and negative delays. Source loss or pause outputs zero; inversion does not turn a missing/paused source into full intensity.

Position rather than velocity: checked maps normalized script height directly to intensity; unchecked averages movement-speed magnitude over 0.6 seconds using the existing full-scale normalization (six full-scale position units per second). Invert script flips the resulting intensity envelope. Thus, in position mode it makes intensity opposite to the authored position; in velocity mode it flips high/low intensity, rather than reversing raw movement direction. VacuGlide’s script sampler uses Gradient where the player supplies it and retains Follow clock jitter correction.

Both file selectors include five original starter funscripts and existing HandyScripts / VacuglideScripts entries. Open accepts an external .funscript or VacuGlide JSON. The two selectors are independent. Handy interprets JSON speed tracks as motion using its existing conversion. VacuGlide reads JSON speed values directly as intensity, regardless of the position/velocity checkbox; its automatic JSON valve events are not replayed by this panel. Use the existing Script Editor for complete valve-script playback.

+stroke introduces air; −stroke invokes the existing minus-valve action. Buttons retain the controller’s existing pulse timing and closure handling and do not create a second device writer.

## Visualisation and limitations

Each device has a last-ten-seconds chart. Handy plots requested positions; VacuGlide plots requested intensity after trim. These are not measured motion or pressure. Each status line retains its device’s confirmation. The transports have different delays; shared Resume does not promise millisecond physical synchronisation. Independent offsets allow alignment. Handy’s first timed preparation can still take longer than a prepared-session restart. Very slow Handy stop/start remains an unresolved physical/timed-path limitation from previous testing.

The established VacuGlide controller still owns leases, trim/cap enforcement, rate-limited motor commands, source-failure stopping and valve closure. Selecting a source in its existing editor hands mapping control back to that editor. No physical device movements were started by the assistant to validate this shared panel.

## Validation

11 shared-panel checks: source mapping, inversion and offsets, paused/missing input, manual intensity and source changes, authored JSON intensity without valve replay, link selection, individual controls, connection preflight, pending-start cancellation, trim/valve closure, source ownership handback, source failure stopping, global STOP and real Tk layout construction. The 60 existing Handy checks and 13 navigation/input/status checks also pass. Standalone startup/shutdown smoke and an offline animated visual preview were checked. Combined physical operation and offset calibration still require operator testing.
