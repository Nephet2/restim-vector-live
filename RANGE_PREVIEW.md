# Alpha84 range-controls preview 3

- Five matching compact response bars, each with two in-track range handles and a live value marker.
- The upper-half handle edits the lower bound; the lower-half handle edits the upper bound. Handles cannot cross. Equal bounds hold a fixed generated value.
- Pulse Frequency, Pulse Rise Time and Pulse Width handles edit the existing Min/Max values directly. No extra final-output remapping is introduced.
- Carrier frequency now has a generated Min/Max range, default 0-1.
- The new Volume response range shapes the primary and prostate running response before base volume, primary ceiling, gain and other downstream modifiers. A zero base volume remains zero. This is not a new hard limit on final transmitted V0.
- Stop, Neutral, recovery-neutral and authored-axis ownership retain alpha84 behaviour. Stop mutes; Neutral centres motion at its existing base volume. Authored passthrough and downstream modifiers are not constrained by these generator ranges.
- Range values persist with the other settings. Default new ranges preserve the original generator response.

Run START_UI_PREVIEW.bat to inspect the expanded bars with all connections blocked. Run start-vector1a.bat for normal operation.

Drag either handle. With a bar focused, Up selects Max, Down selects Min; Left/Right adjusts by .01 and Shift+Left/Right by .05. Numerical Min/Max controls remain available.

Preview 3 changes:
- Main sections now scroll vertically with a scrollbar at the right edge and mouse wheel over the main content. Start/Resume, Neutral and Stop stay fixed in the toolbar. Popup windows and wheel-operated input fields keep their own wheel behaviour.
- Volume response is now three compact rows: settings, response bar with adjacent Min/Max, then matching/help and outgoing V0. Full explanation is under Explain volume.
- Volume output calculation is unchanged from preview 2. A response of .3928 with primary ceiling .85 gives outgoing V0 .33388, displayed as .3339.
- GUI checks cover a 720px-high window, wheel scrolling, reaching bottom diagnostics, scroll-region updates on collapse, and compact volume height.

Preview 2 changes:
- Moved the single persisted Match intensity across spatial modes checkbox and its explanation from Howl conversion to Volume response. It affects PRIMARY volume across spatial modes, not prostate volume.
- Matched intensity and direct Howl amplitude are bounded by the primary response's idle floor and current return-ramp ceiling before the primary volume ceiling and later overlays. With defaults, rest is approximately .38 of the primary ceiling, not exactly .40: the existing speed ratio contributes .95 x .40.
- Added outgoing Primary/Prostate V0 command readouts after authored routing, gain and events. These are calculated outgoing commands, not confirmed device readings; a disconnected transport or suppressed V0 axis will not update ReStim. Stop reports zero; Neutral reports the existing base-volume command.
- Prostate output is unchanged. Base volume .70 sets its generated maximum; primary uses its separate ceiling. With speed ratio 20 and prostate multiplier 1.5, active prostate output is about .677-.700, and its .70 rest factor gives about .474 at idle. The multiplier compresses active variation; it does not multiply amplitude.

Validation: 295 tests and 12 subtests, including actual Tk drag/equal-handle behaviour, loaded/saved ranges, zero volume and compact geometry at 1360 and 1920 pixel window widths. No physical hardware exercised by automated checks.
