# Vector 1A 1.6.0-alpha68

First deterministic funscript-modifier commissioning build.

- Adds a **Script modifiers** commissioning window.
- Manual controls only; no Gwendolyn/Director modifier actions yet.
- The authored L0 input remains immutable underneath the modifier layer.
- Adds bounded deterministic controls for stroke amplitude scale, global range scale, position bias, and curve smoothing.
- Adds a configurable transition ramp (default 0.75 s) so enabling, disabling, or changing the modifier target blends rather than hard-jumping.
- Reset returns to neutral authored motion.
- Modifier settings persist with normal Vector settings.
- Existing MFP → Vector → ReStim, timeline, Director, stop/resume, and MPC clock paths are otherwise unchanged.

Commissioning intent: prove that the modifier layer is perceptibly useful, reversible, continuous, bounded, and preserves the original authored script before exposing any modifier control to Gwendolyn.
