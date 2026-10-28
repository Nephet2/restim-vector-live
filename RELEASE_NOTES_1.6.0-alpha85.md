# Vector 1A 1.6.0-alpha85

Adds output response ranges and makes the growing control window easier to use.

## Changes
- Compact Min/Max handles on Volume response, Frequency, Pulse frequency, Pulse rise time and Pulse width bars. Upper handle sets Min; lower handle sets Max. Numerical inputs remain available and settings persist.
- Pulse handles edit their existing bounds directly. Volume and carrier gain generated response bounds; defaults are 0-1. No additional final-output scaling is introduced.
- Main sections have a right-hand vertical scrollbar and mouse-wheel scrolling. Start/Resume, Neutral and Stop remain fixed at the top.
- Volume response is condensed to three rows. Match intensity across spatial modes is now here, with an Explain volume button.
- Primary spatial intensity matching and direct Howl amplitude respect the running response's idle floor and return-ramp ceiling. They previously replaced that response and could force zero volume at rest.
- Separate outgoing Primary and Prostate V0 command readouts include later gain, events and authored overrides. They are calculated commands, not device acknowledgements.
- Retains alpha84 Custom Curves, responsive connections and carrier C0 on both outputs.

## Volume interpretation
The response bar is before the primary ceiling and subsequent modifiers. For example, response 0.3928 with primary ceiling 0.85 gives primary V0 0.3339 when matching and other modifiers are inactive.

The existing speed ratio affects the rest response: default ratio 20 and rest level 0.4 produce a normalized idle response around 0.38, before the primary ceiling. Matching respects this response; later explicit gains, events and authored overrides retain their output ownership.

Prostate calculation is unchanged. It uses Base volume as its generated maximum, not Primary volume ceiling. At base 0.70, ratio 20 and prostate ratio multiplier 1.5, active generated output is approximately 0.677-0.700; its default rest factor 0.70 gives approximately 0.474 at idle. The multiplier compresses variation, not amplitude gain.

Stop still mutes. Neutral retains alpha84's centered motion and base-volume command. Response ranges are not final transmitted V0 limits for explicit authored overrides or downstream modifiers.

## Install
Python source release; no executable included. Extract the complete Vector1A-1.6.0-alpha85-source-windows.zip and run start-vector1a.bat. Python 3.11+ is required; Python 3.13 x64 is recommended for the bundled Pillow dependency.

Close Vector and copy profile/Vector1A/settings.json from your previous installation into the matching location in the new folder. Public downloads contain no personal settings.

## Validation
295 tests and 12 subtests pass locally on Windows/Python 3.13. GUI regressions exercise range handles, persistence, compact layout, mouse-wheel scrolling, bottom-section reachability at a 720px window height, and scroll-region changes on collapse. Command regressions cover primary rest output, the 0.3928 x 0.85 example, prostate preservation, authored overrides, Stop and Neutral. Extracted source startup is checked with connections disabled. Automated tests do not exercise physical hardware.
