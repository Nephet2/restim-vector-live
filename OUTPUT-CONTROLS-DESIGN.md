# Shared output panel — implemented

Goal: Handy controls physical motion; VacuGlide controls intensity. Implemented after the operator confirmed improved Handy response. See MOTION-INTENSITY.md for current behaviour and validation.

| Control | Handy | VacuGlide |
|---|---|---|
| Link to shared transport | Independent checkbox | Independent checkbox |
| Source | Funscript / Script library / Manual, mutually exclusive | Funscript / Script library / Manual, mutually exclusive |
| Invert | Invert authored position within range | Independent inversion of mapped intensity |
| Main slider | Two handles for stroke range, with timed target marker | Intensity trim, respecting existing limits |
| Tempo | Continuous 0.25–2× plus presets | Follow its selected source clock; link selects shared Pause/Resume only |
| Manual | Native motor speed; optional timed Gradient strokes | Manual intensity |
| Time offset | Signed seconds, positive leads / negative delays | Independent signed offset when using a script |
| Stroke buttons | — | +stroke introduces air; −stroke retains existing device meaning |
| Position mode | Physical position trajectory | Checked: script position maps to intensity; unchecked: movement velocity maps to intensity |

One shared Pause/Resume acts on linked outputs. Unlinked outputs retain individual controls. The existing Vector STOP continues to stop every output regardless of link selection. A failed resume of one output must be shown separately, never presented as an all-device success. Mode/source changes coalesce while pending, stop the prior backend before starting another, and never revive motion after an operator pause. Linking a device must not itself start it.

Handy and VacuGlide use different transports and latencies. A shared button coordinates requested state; it does not establish millisecond physical synchronisation. Keep per-device confirmation and latency visible.

For velocity mode, distinguish inversion of the resulting intensity envelope from inversion of the input position: the magnitude of d(1−x)/dt equals the magnitude of dx/dt. Inverting raw position alone therefore cannot make unsigned velocity intensity opposite-phase. Position mode provides the direct high/low intensity relation Steve described.

Reuse VacuGlideControl as the output owner, retaining its leases, trim limits, valve timing and stop handling. Extend its source-to-intensity mapping rather than adding a second writer to the device. Handy now exposes source, inversion, offset, Gradient, range, tempo, and resumable mode handoffs for this later panel.
