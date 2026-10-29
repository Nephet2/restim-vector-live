# Parameter response curves

Open Edit primary response curves, to the left of the Volume response bar, for the shared six-curve editor. START_CURVE_PREVIEW.bat opens it with all connections blocked; start-vector1a.bat runs the normal application.

## Live editing
Double-click to add a point, drag points and right-click an interior point to remove it. Endpoint input positions remain at 0 and 100 percent; their output values can move. Choose linear or bounded smooth interpolation, or a shape preset. Each curve accepts 2-24 points, which cannot cross.

Edits apply immediately to generation and save automatically. There is no Apply button. Output already in the look-ahead buffer follows after the configured delay. Restore opening curves returns all six to their state when the editor opened; Reset all to straight restores neutral diagonal responses.

## What the axes mean
Each graph maps an existing calculated response within its output range to a new position within the same Min/Max range. X is normalized calculated input; Y is output within that range, both 0-100 percent. This is not a timeline; the input need not visit every part of the graph.

Primary volume and Prostate volume curves independently shape generated response before Primary volume ceiling or prostate Base volume scaling. Primary intensity matching uses the shaped idle bound. Base volume zero remains zero. The curves can change the running and rest response. Later gain, events and authored overrides retain ownership of their final output.

Frequency uses its ramp/speed mixture. Pulse frequency uses its speed/alpha mixture with the existing rest/attack response. Pulse rise time uses its inverted ramp/speed mixture. Pulse width uses its existing bounded speed/inverted-position response, preserving the legacy width clamp. Explicit authored parameter axes and Howl pulse overrides keep their existing ownership. Stop, Neutral and spatial E1-E4 geometry are unchanged.

## Profiles
Save profile captures all six curves, interpolation and a description. Saving the same name replaces its stored shapes. Select and Load profile applies it live. Update description leaves stored curves unchanged. Loading preserves the current Min/Max settings. Old four-parameter preview profiles gain neutral volume curves without changing their existing shapes.

Profiles and active curves persist in the usual profile/Vector1A/settings.json file. Copy that file from your previous installation after closing Vector to retain your settings. Public packages contain no personal settings.

## 3D composite
Drag to rotate; Reset view restores the initial camera. X is calculated input, height is response within the output range and depth separates the six parameters into coloured lanes. Each lane has its own current-input marker. Volume lanes are before ceiling / base-volume scaling. The markers show calculation state, not confirmed output received by ReStim. Drag the divider to resize the graph and composite panels. Scroll the graph cards to reach lower curves.

## Defaults
Neutral straight diagonals preserve alpha85 calculations. Match intensity across spatial modes and Scale optional effects with speed default to unchecked for new settings. Explicitly saved choices remain in effect.
