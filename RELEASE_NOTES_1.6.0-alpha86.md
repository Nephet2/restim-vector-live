# Vector 1A 1.6.0-alpha86

Adds live editable parameter-response curves to alpha85.

## New response editor
- Independent curves for Primary volume, Prostate volume, Frequency (C0), Pulse frequency (P0), Pulse rise time (P3) and Pulse width (P1).
- Double-click to add points, drag to reshape and right-click an interior point to remove it. Choose linear or bounded smooth interpolation and shape presets.
- Edits apply live to generation and save automatically. Existing look-ahead means buffered output follows later. No Apply button.
- Named custom profiles store all six curve shapes, interpolation and a description. Save updates a same-name profile; Load applies it live. Descriptions can be updated independently. Current Min/Max ranges stay unchanged when a profile loads.
- Rotatable six-lane 3D response composite, independent input markers, Reset view and resizable panels. The graph cards scroll vertically.
- One Edit primary response curves button sits left of the Volume response bar on its existing row, opening the shared editor for all six curves. No extra per-bar button rows.

## Defaults and compatibility
Match intensity across spatial modes and Scale optional effects with speed are unchecked by default for new profiles. Explicitly saved checkbox choices are retained; untick them once if your copied settings have them enabled.

Neutral straight diagonals preserve previous calculations. Four-parameter preview profiles gain neutral volume curves when migrated. Public downloads include no personal settings or custom profiles.

## Curve interpretation
Graphs map an existing normalized generated response to an output position within its Min/Max range. They are response functions, not timelines or physical electrode paths; the input need not traverse the full graph. Each parameter can have a different current input, so each 3D lane has its own marker.

Volume curves act on generated response before the primary ceiling / prostate Base volume. They can change rest response too. Primary intensity matching uses the shaped idle bound; Base volume zero still mutes both. Later explicit gains, events and authored overrides retain ownership. The parameter curves do not change E1-E4 spatial geometry. Existing authored axes and Howl pulse overrides can replace generated parameter values.

Stop still mutes; Neutral retains the prior centred-motion/base-volume command. The reported intermittent prostate-beta hold at 0.5 with MFP input is not changed in this release.

## Install
Download Vector1A-1.6.0-alpha86-source-windows.zip, extract the whole folder and run start-vector1a.bat. This is a Python source release, with no executable. Python 3.11+ is required; Python 3.13 x64 is recommended for the bundled Pillow dependency.

Close Vector and copy your existing profile/Vector1A/settings.json into the same location in the new folder to retain preferences and custom profiles. START_CURVE_PREVIEW.bat opens the curve editor with all connections disabled for inspection.

## Validation
304 tests and 12 subtests pass locally on Windows/Python 3.13. Checks cover exact default calculations, live point editing, automatic persistence, named profiles, legacy migration, independent volume curves and shaped rest bounds, zero base volume, bounded interpolation, six-lane projection/rotation, compact button placement and saved/default checkbox choices. Release publication is gated on Windows tests under Python 3.11, 3.13 and 3.14 plus an extracted source startup check with connections disabled. No physical hardware is exercised by automated checks.
