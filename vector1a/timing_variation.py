"""Endpoint-locked primary timing experiment; no transport or device ownership."""
import copy
import math
from dataclasses import replace

STYLES=('Stroke groups','Accelerate','Decelerate','Dwell & return')
GROUP_PATTERN=('Linear','Accelerate','Accelerate','Linear',
               'Decelerate','Decelerate','Dwell & return','Linear')

def group_style(sequence,multiplier=1):
    return GROUP_PATTERN[((sequence-1)//multiplier)%len(GROUP_PATTERN)]

def warp(progress,style):
    p=min(1.,max(0.,progress))
    if style=='Accelerate':return p*p,2*p
    if style=='Decelerate':return 1-(1-p)**2,2*(1-p)
    if style=='Dwell & return':
        if p<=.12:return 0.,0.
        u=(p-.12)/.88
        return u*u*(3-2*u),6*u*(1-u)/.88
    return p,1.

class TimingVariation:
    def __init__(self):
        self.enabled=False;self.style=STYLES[0];self.amount=.65;self.group_multiplier=1
        self.reset()

    def reset(self):
        self.strength=0.;self.key=None;self.active_style='Linear';self.applied_strength=0.
        self.status='OFF';self.pulse_state={};self.frames=0
        self.readback={}

    def configure(self,enabled,style,amount,group_multiplier=1):
        if style not in STYLES:raise ValueError('Unknown timing style')
        amount=float(amount)
        if not math.isfinite(amount):raise ValueError('Timing amount must be finite')
        n=float(group_multiplier)
        if not math.isfinite(n) or not n.is_integer() or not 1<=n<=32:
            raise ValueError('Group multiplier must be a whole number from 1 to 32')
        self.enabled=bool(enabled);self.style=style;self.amount=max(0.,min(1.,amount))
        self.group_multiplier=int(n)

    def snapshot(self):
        return dict(enabled=self.enabled,style=self.style,amount=self.amount,group_multiplier=self.group_multiplier,
                    applied_style=self.active_style,applied_strength=self.applied_strength,
                    status=self.status,modified_frames=self.frames,**self.readback)

    def apply(self,engine,sample):
        stroke=sample.timing_stroke
        if not self.enabled and self.strength==0:
            self.status='OFF';self.readback={};return sample
        if stroke is None or stroke.duration<=0:
            self.status='Waiting for completed stroke / more look-ahead'
            self.applied_strength=0.;self.readback={};return sample
        key=(stroke.sequence,stroke.start_time,stroke.end_time)
        if key!=self.key:
            self.key=key
            # Never begin retiming partway through a stroke that already left
            # the queue before its reversal was observed.
            if sample.calculated_at>stroke.start_time+1.5/engine.rate_hz:
                self.applied_strength=0.
                self.readback={}
                self.status='Stroke bypassed: increase look-ahead';return sample
            target=self.amount if self.enabled else 0.
            self.strength+=max(-.2,min(.2,target-self.strength))
            self.applied_strength=self.strength
            self.active_style=self.style
            if self.style=='Stroke groups':
                self.active_style=group_style(stroke.sequence,self.group_multiplier)
        if not self.applied_strength:
            if not self.enabled:self.status='OFF';self.readback={}
            return sample
        if self.active_style=='Linear':
            self.status='ACTIVE: regular stroke'
            self.readback=dict(baseline_pulse_frequency=sample.pulse_frequency,
                output_pulse_frequency=sample.pulse_frequency,
                baseline_pulse_width=sample.pulse_width,output_pulse_width=sample.pulse_width)
            return sample
        amount=self.applied_strength
        p=stroke.progress(sample.calculated_at)
        q,derivative=warp(p,self.active_style)
        q=p+(q-p)*amount;derivative=1+(derivative-1)*amount
        source=engine._jitter_segment(engine._modified_segment(stroke,sample.calculated_at),sample.variation_depth)
        speed=min(100.,max(0.,stroke.speed_percent*derivative))
        warped=replace(source,measured_speed_percent=speed)
        a,b,pos,_=engine.calculator.calculate(sample.mode,warped,
            source.start_time+q*source.duration,engine.params,
            engine.spatial_curve,engine.spatial_blend*sample.variation_depth)
        # Reuse the real pulse mappings with independent output-order attack
        # state. Never replay old timestamps into the live calculator's state.
        context=copy.copy(engine)
        context._parameter_curve_live=dict(engine._parameter_curve_live)
        context.__dict__.update(self.pulse_state)
        context._last_input_time=sample.calculated_at
        pf=context._calculate_pulse_frequency(sample.calculated_at,speed,a)
        pw=context._calculate_pulse_width(sample.calculated_at,speed,pos)
        self.pulse_state={k:getattr(context,k) for k in (
            '_pulse_was_active','_pulse_active_since','_width_was_active','_width_active_since')}
        # Blend exact baseline commands in/out; retain its voltage/volume,
        # carrier, rise time, L0 and secondary pulse commands.
        aa=sample.alpha+(a-sample.alpha)*amount
        bb=sample.beta+(b-sample.beta)*amount
        pp=sample.pulse_frequency+(pf-sample.pulse_frequency)*amount
        ww=sample.pulse_width+(pw-sample.pulse_width)*amount
        self.status='ACTIVE: '+self.active_style;self.frames+=1
        self.readback=dict(effective_speed_percent=round(speed,1),position=round(pos,4),
            baseline_pulse_frequency=sample.pulse_frequency,output_pulse_frequency=pp,
            baseline_pulse_width=sample.pulse_width,output_pulse_width=ww)
        return replace(sample,alpha=aa,beta=bb,pulse_frequency=pp,pulse_width=ww,
                       secondary_pulse_frequency=sample.pulse_frequency,
                       secondary_pulse_width=sample.pulse_width)
