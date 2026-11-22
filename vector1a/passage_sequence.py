"""Ceiling-relative musical phrases: baseline -> destination -> baseline."""
from dataclasses import dataclass, asdict
from .passage import number, ease

PRESETS = ('build_release', 'tease_return')


@dataclass(frozen=True)
class SequencePlan:
    steps: tuple
    baseline: float
    clock: str = 'elapsed'
    label: str = 'Narrative sequence'
    transition_seconds: float = 5.0
    target: str = 'primary'
    kind: str = 'ceiling_sequence'

    @classmethod
    def validated(cls, body, baseline):
        baseline = number(baseline, 'primary ceiling baseline', .01, 1)
        if not isinstance(body, dict) or set(body)-{'steps','clock','label','transition_seconds'}:
            raise ValueError('Invalid sequence fields')
        steps = body.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
            raise ValueError('Sequence requires 1 to 16 steps')
        clean = []
        for step in steps:
            if not isinstance(step, dict) or set(step)-{'preset','out_seconds','hold_seconds','return_seconds','level'}:
                raise ValueError('Invalid sequence step fields')
            preset = step.get('preset')
            if preset not in PRESETS:
                raise ValueError('Unknown sequence preset')
            out = number(step.get('out_seconds',30), 'out_seconds', 2, 180)
            hold = number(step.get('hold_seconds',10), 'hold_seconds', 0, 120)
            back = number(step.get('return_seconds',30), 'return_seconds', 2, 180)
            level = number(step.get('level', 1 if preset=='build_release' else baseline*.65), 'level', 0, 1)
            if preset=='build_release' and level < baseline:
                raise ValueError('Build destination must be at or above the primary ceiling')
            if preset=='tease_return' and level > baseline:
                raise ValueError('Tease destination must be at or below the primary ceiling')
            clean.append(dict(preset=preset,out_seconds=out,hold_seconds=hold,return_seconds=back,level=level))
        if sum(s['out_seconds']+s['hold_seconds']+s['return_seconds'] for s in clean)>1800:
            raise ValueError('Sequence must last at most 30 minutes')
        clock = body.get('clock','elapsed')
        if clock not in ('elapsed','media'): raise ValueError('Unknown clock')
        label = body.get('label','Narrative sequence')
        if not isinstance(label,str) or len(label)>160: raise ValueError('Label too long')
        transition=number(body.get('transition_seconds',5),'transition_seconds',2,15)
        return cls(tuple(clean),baseline,clock,label,transition)

    @property
    def duration(self):
        return sum(s['out_seconds']+s['hold_seconds']+s['return_seconds'] for s in self.steps)

    @property
    def max_factor(self):
        return 1/self.baseline

    def detail_at(self,elapsed):
        t=max(0,elapsed)
        game_label=''.join(c for c in self.label.lower() if c.isalpha())
        is_game='redlight' in game_label and 'greenlight' in game_label
        for index, step in enumerate(self.steps):
            duration=step['out_seconds']+step['hold_seconds']+step['return_seconds']
            if t < duration:
                if t < step['out_seconds']:
                    phase='build' if step['preset']=='build_release' else 'tease'
                    level=self.baseline+(step['level']-self.baseline)*ease(t/step['out_seconds'])
                elif t < step['out_seconds']+step['hold_seconds']:
                    phase='hold';level=step['level']
                else:
                    phase='release' if step['preset']=='build_release' else 'return'
                    frac=(t-step['out_seconds']-step['hold_seconds'])/step['return_seconds']
                    level=step['level']+(self.baseline-step['level'])*ease(frac)
                return dict(step_index=index,preset=step['preset'],phase=phase,ceiling=level,
                            game_phase=('red_light' if step['preset']=='tease_return' else 'green_light') if is_game else None)
            t-=duration
        return dict(step_index=len(self.steps)-1,preset=self.steps[-1]['preset'],phase='complete',ceiling=self.baseline,game_phase=None)

    def at(self,elapsed):
        d=self.detail_at(elapsed)
        return d['phase'],d['ceiling']/self.baseline

    def preview(self):
        return [dict(seconds=self.duration*i/300,**self.detail_at(self.duration*i/300)) for i in range(301)]
