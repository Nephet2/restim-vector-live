# Vector 1A 1.6.0-alpha59

- Adds independent bounded Top Spatial Gain and Bottom Spatial Gain.
- Increase/decrease are cumulative using operator-set percentage steps; Restore returns to 100%.
- Defaults: 10% step, 50–150% bounds, smooth 20 percentage-points/second ramp.
- Spatial gain changes final V0 intensity while preserving anatomical focus location.
- Authored primary V0 is included after source routing.
- Director API adds `/v1/spatial-gain/top` and `/v1/spatial-gain/bottom` with increase/decrease/restore actions.
- Director state reports target/effective gain, selected duration, previous target/duration, step, bounds and ramp.
- Replaces the obsolete volume-authority warning with a ReStim calibration note.
- 137 automated tests pass.
