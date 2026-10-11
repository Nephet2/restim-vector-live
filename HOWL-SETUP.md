# Vector with Howl conversion

Run `start-vector1a.bat` from this folder. This experimental build is based on
your Vector 1A alpha77 installation. The original Desktop installation is unchanged.
The launcher keeps this build's settings under `profile/Vector1A/settings.json`.
Configure the MFP and ReStim connections as in Vector's existing setup guide.

Expand **Four-phase primary motion** and select **Howl Positional** or
**Howl Dynamic** in **Spatial model**. The **Howl conversion** controls are
at the bottom of that section. Defaults follow Howl's width .35, dynamic
panning .8, amplitude boost .8 and smoothing sigma .2 seconds.

These modes use incoming raw L0 (including its inversion option), with
velocity normalized to five full-range movements per second. They bypass
Vector's generated spatial path, crossover, sequence morphing and group delay.
The selected static electrode order still applies. Volume ceiling, focus,
gain, volume textures, authored overrides and Director events remain available
and can change the result. Select only L0 from MFP to hear the generated
conversion without authored electrode, volume or pulse overrides.

Electrode order matters: Howl's logical first electrode is low and its fourth
is high. Vector's anatomical labels may assume a different physical setup;
choose an appropriate signalling sequence for your connections.

The optional **Howl pulse frequency and low-frequency thump** checkbox uses a
1–100 Hz frequency range, five base carrier cycles, and adjustable thump strength (default .5).
Before enabling it, set ReStim's TCode/funscript axis ranges to **P0: 1–100 Hz**
and **P1: 3–20 carrier cycles**, with linear scaling for both. Carrier frequency
and pulse rise time remain Vector controls. For Howl's default carrier/rise
behaviour, configure their physical outputs to 1300 Hz and five cycles in
Vector/ReStim. ReStim master volume, current limits, calibration and optional
frequency/tau compensation also affect physical output.

This is an adaptation for streamed L0, not an exact reproduction of playing a
file in Howl. MFP supplies interpolation and normalization; incoming positions
are differentiated and smoothed instead of using Howl's Hermite script
derivatives. Multi-axis energy, Howl's effects and output calibration are not
ported. Its signed-distance positional weight formula is preserved as written
in upstream source, rather than replaced with a symmetric interpretation.

Validation: 182 unittest cases passed; GUI construction, refresh and mocked
output checks passed for both Howl modes and both original spatial models.
No physical FOC-Stim test was performed. Compare with hardware disconnected
first, then evaluate at a low device setting.

Sources:
- https://github.com/Amethyst-Sysadmin/Howl/blob/master/app/src/main/java/com/example/howl/Funscript.kt
- https://github.com/Amethyst-Sysadmin/Howl/blob/master/app/src/main/java/com/example/howl/OutputFOC.kt
- https://github.com/Amethyst-Sysadmin/Howl/wiki/FOC-Stim-output


## Optional TCode output (howl2)

Each Frequency, Pulse frequency, Pulse rise time and Pulse width heading has
an independent **Send TCode** checkbox. They are enabled by default and saved
with application settings. Uncheck any axis to let ReStim control that value.
This suppresses Frequency C0 (primary) / F0 (secondary), Pulse frequency P0,
Pulse rise time P3 and Pulse width P1 on both output connections, including
manual previews, Howl pulse conversion, Director events and authored overrides.
Other axes, including volume and electrode position, continue normally.

After unchecking, set the desired static value in ReStim. Omitting TCode does
not reset a value previously received by ReStim. Rechecking resumes Vector's
updates. For dynamic Howl pulse frequency with static carrier, pulse width and
rise time, enable the Howl pulse option, leave Pulse frequency checked and
uncheck the other three. P0 must still use the documented 1–100 Hz axis range.

The roll-up buttons now use + (expand) and - (collapse), and previously
corrupted UI text has been repaired.


## Gwendolyn controls (howl3)

Primary spatial now offers Top — Howl Positional and Top — Howl Dynamic.
These choices select the same modes as the main Spatial model dropdown, and
the two controls stay synchronized. The Director API advertises and accepts
`top_howl_positional` and `top_howl_dynamic`, and reports the active mode.


Thump strength is adjustable from 0 to 1 in Howl conversion: 0 disables the
low-frequency width boost; 1 gives its maximum boost. It affects output only
when the Howl pulse option and Pulse width Send TCode are both enabled.


## Howl calibration adjustments

Howl conversion now includes Pulse min/max in Hz (1–100), Frequency balance A/B
(0–1, neutral .5), Amplitude scaling (0–1, default 1), and Positional effect
(0–1, default 1). These are saved in settings and four-phase presets.
Balance attenuates stronger frequency regions: below .5 reduces high frequencies;
above .5 reduces low frequencies. Scaling reduces both stereo amplitudes before
FOC conversion. The positional control adjusts stereo panning; in Positional
mode Howl reverses this encoding, so nonzero strengths generally preserve the
original position at neutral calibration, while zero centres it. Frequency
balance can alter the recovered position. Sensation width is a separate control.
Pulse range applies only when Howl pulse output and P0 Send TCode are enabled.
ReStim's P0 axis mapping must remain linear 1–100 Hz even for a narrower selected
range. If min exceeds max, the effective max is clamped to min.


## Matching spatial-mode intensity

Match intensity across spatial modes is enabled by default. All four modes use
one continuous movement-based RMS stereo amplitude envelope, including Howl's
amplitude scaling, frequency balance and slow-motion boost. Switching the
spatial model does not reset that envelope. Moving Focus and Depth Spread use
this envelope instead of their previous generated volume response; deselect the
checkbox to restore the individual modes' volume behaviour. The primary ceiling,
gain and volume overlays still apply. Authored V0 overrides and Director events
can replace the matched volume. Different electrode distributions and pulse
settings can still feel different even with identical volume commands; physical
matching has not been tested on hardware.


## Automatic ready startup

Enabled by default under Session startup: automatically starts the MFP listener,
resumes the engine, and connects Primary ReStim at the saved address. ReStim
connection retries in the background if it is not yet available or disconnects.
Stop still stops output; reconnection does not press Resume again. Disable the
option for manual startup. Application launching and secondary ReStim startup
remain controlled by the existing optional Auto-start application selections.
