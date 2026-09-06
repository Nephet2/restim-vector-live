# Vector 1A 1.6.0-alpha55

- Replaces the experimental Area of Effect semantic model with anatomical Spatial Focus.
- Adds captured Top Spatial Focus profiles: Glans Focus, Shaft Focus, Lower Shaft Focus, Root Focus, Top Sweep, Top Full.
- Adds captured Bottom Spatial Focus profiles: Prostate Focus, Anal Focus, Perineum Focus, Bottom Sweep, Bottom Full.
- Exposes the anatomical map in Director state/capabilities:
  - Top: E1 glans, E2 shaft, E3 lower shaft, E4 root.
  - Bottom: A prostate, B anus, C testicles/perineum.
- Adds `/v1/semantic/top-focus` and `/v1/semantic/bottom-focus`.
- Keeps Primary Spatial behaviour (Top Moving Focus / Top Depth Spread) independent from anatomical focus.
- Removes the Alpha 54 Area of Effect endpoint from the current Director API.
- No change to the deterministic signal-engine cadence, queue, routing or ReStim output path.
