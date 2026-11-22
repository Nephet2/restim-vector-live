"""Howl-inspired L0 streaming conversion; no hardware or network side effects.

FOC electrode and amplitude formulas adapted from Amethyst-Sysadmin/Howl
(MIT; see THIRD_PARTY_NOTICES.md). Live MFP samples replace file interpolation.
"""
from collections import deque
from dataclasses import dataclass
import math


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value)) if math.isfinite(value) else low


def constrain(weights):
    total = sum(weights)
    pedestal = max(0.0, math.sqrt(sum(w*w for w in weights)) - total / 2)
    values = tuple(w + pedestal for w in weights)
    peak = max(values)
    return tuple(v / peak for v in values) if peak > 1e-9 else (1.0,) * 4


def positional(position, width=.35):
    p, spread = clamp(position) * 3, 1 + clamp(width) * 3
    # Preserve upstream's signed-distance formula exactly, including broad
    # support toward earlier electrodes; do not silently substitute abs().
    def weight(i):
        d = (p-i) / spread
        return math.cos(d * math.pi / 2)**2 if d <= 1 else 0.0
    return constrain(tuple(weight(i) for i in range(4)))


def dynamic(amp_a, amp_b, freq_a, freq_b, strength=.8):
    if max(amp_a, amp_b) < 1e-4:
        return (1.0,) * 4
    s = clamp(strength)
    values = []
    for amp, freq in ((amp_a, freq_a), (amp_b, freq_b)):
        angle = clamp(freq) * math.pi / 2
        values.extend(amp * ((1-s)*.5+s*x) for x in
                      (math.cos(angle)**2, math.sin(angle)**2))
    return constrain(tuple(values))


@dataclass(frozen=True)
class Frame:
    electrodes: tuple
    volume: float
    frequency: float
    matched_volume: float = 0.0


class LiveConversion:
    def __init__(self):
        self.history = deque()
        self.previous = None

    def sample(self, time, position, mode, width=.35, pan=.8, boost=.8, sigma=.2,
               balance_a=.5, balance_b=.5, scaling=1.0, strength=1.0):
        position = clamp(position)
        sigma = clamp(sigma, .01, 1.0)
        velocity = 0.0
        if self.previous is not None:
            last_time, last_position = self.previous
            dt = time-last_time
            if dt <= 0 or dt > 1:
                self.history.clear()
            else:
                velocity = (position-last_position)/dt
        self.previous = (time, position)
        norm = clamp(velocity/5, -1, 1)
        self.history.append((time, norm*norm))
        while self.history and self.history[0][0] < time-3*sigma:
            self.history.popleft()
        weighted = [(math.exp(-((time-t)/sigma)**2/2), energy)
                    for t, energy in self.history]
        raw = math.sqrt(sum(w*e for w, e in weighted)/sum(w for w, _ in weighted))
        amp = 0.0 if raw < .005 else clamp(raw)**max(.001, 1-clamp(boost))
        strength = clamp(strength)
        effective = .5*(1-strength) + position*strength
        a, b = amp*math.sqrt(1-effective), amp*math.sqrt(effective)
        core = position*.8 + raw*.2
        fa, fb = clamp(core-norm*.15), clamp(core+norm*.15)
        def frequency_scale(balance, freq):
            balance = clamp(balance)
            reduction = 2*abs(balance-.5)
            return 1-reduction*(freq if balance < .5 else 1-freq)
        a = clamp(a*frequency_scale(balance_a, fa)*clamp(scaling))
        b = clamp(b*frequency_scale(balance_b, fb)*clamp(scaling))
        if mode == "Howl Positional":
            # Reverse the stereo positional encoding as in Howl's FOC output.
            if a == 0 and b == 0:
                recovered, recovered_amp = .5, 0.0
            elif b == 0:
                recovered, recovered_amp = 0.0, a
            elif a == 0:
                recovered, recovered_amp = 1.0, b
            else:
                effective_pos = 1/(1+(a/b)**2)
                recovered_amp = (a/math.sqrt(1-effective_pos) if effective_pos < .5
                                 else b/math.sqrt(effective_pos))
                recovered = clamp((effective_pos-.5*(1-strength))/strength) if strength > 0 else .5
            electrodes, volume = positional(recovered, width), clamp(recovered_amp)
        else:
            electrodes, volume = dynamic(a, b, fa, fb, pan), max(a, b)
        freq = (fa*a+fb*b)/(a+b) if a+b > 1e-6 else fa
        return Frame(electrodes, clamp(volume)**.6, freq, clamp(math.sqrt(a*a+b*b))**.6)
