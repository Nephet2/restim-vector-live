# Civet pressure volume control

Signal Lab: click **Pressure sensor...** beside the output-volume controls.
Vector1A-Howl: click **Pressure** beside STOP in the top toolbar.

1. Disconnect Civet from the MP3 player or other app first. Only the app you are
   using should connect to the sensor.
2. Make the sensor Bluetooth icon yellow, then click Connect Civet promptly.
3. Set A (restore), B (reduce), reduction %, response and recovery seconds.
4. Tick Enable pressure reduction and click Apply settings. Connection alone does
   not enable control. Every application launch starts with control disabled.

Defaults: A=21 kPa, B=22 kPa, reduce by 20%. At B, volume approaches 80% of normal;
it stays reduced until pressure reaches A, then approaches normal volume. Response
and recovery use exponential smoothing, matching the player's principle. Each app
saves its own threshold settings; the enabled state and fault state are not saved.

The multiplier is applied after signal generation in Signal Lab and at final socket
send in Vector. Vector's primary and secondary V0 output, authored overrides,
events and neutral paths are covered. Other signal parameters and requested levels
are unchanged. While enabled, pressure control owns V0 even if V0 is deselected in
Vector's axis controls. Stop still sends zero; no volume change compounds itself.

If readings are stale/disconnected, output is held at zero. Signal Lab disarms;
Vector stops its engine. Reconnection does not clear the hold. Untick Enable and
Apply (this stops output), reconnect, then enable and Apply. Re-arm/resume output
explicitly when ready. Gwendolyn has no control over these settings and is instructed
not to compensate for the sensor's reduction by raising requested levels.

The existing Gwendolyn launcher paths are unchanged. Restart any already-open output
application and Gwendolyn to load the update. This update does not start output or
automatically connect the sensor.

Validation: 191 Vector/new pressure tests passed; 41 of 42 Signal Lab checks passed.
The remaining test also fails before this update: it expects 27 reference sessions,
while 30 are present. New checks cover both pressure thresholds, holding the reduction,
PCM scaling, authored V0 overrides, both Vector lanes, stale data, fault latching,
audio-worker disarm and socket reconnection. Physical output was mocked, not exercised.
