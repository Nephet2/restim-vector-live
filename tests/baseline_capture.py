"""Deterministic capture of real composition/serialization with all external I/O blocked."""
import json, os, socket, sys, threading
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

def capture(root_path, worker_check=False, extended=False):
 real_start, real_join = threading.Thread.start, threading.Thread.join
 owner = threading.get_ident()
 sys.path[:0]=[str(root_path),str(root_path/'dependencies')]
 import tkinter as tk
 from vector1a.app import VectorApp
 from vector1a.engine import VectorEngine, OutputSample
 from vector1a.motion import MotionMode
 from vector1a.fourphase import SPATIAL_MODELS
 from vector1a.tcode import TCodeCommand
 from vector1a.parameter_curves import default_curves

 def blocked(*a,**kw): raise AssertionError('External I/O forbidden in command baseline')
 def decode(frame):
  size=frame[1]&127; i=2
  if size==126: size=int.from_bytes(frame[2:4],'big'); i=4
  mask=frame[i:i+4]; payload=frame[i+4:i+4+size]
  return bytes(v^mask[k%4] for k,v in enumerate(payload)).decode()
 class FakeSocket:
  def __init__(self, frames): self.frames=frames
  def sendall(self,frame): self.frames.append(decode(frame))
  def shutdown(self,*a): pass
  def close(self): pass
 records={}
 with ExitStack() as guards:
  if worker_check:
   for cls in (tk.Variable,tk.StringVar,tk.BooleanVar,tk.DoubleVar,tk.IntVar):
    for name in ('get','set'):
     original=getattr(cls,name)
     def checked(self,*args,_original=original,**kwargs):
      assert threading.get_ident()==owner, 'Output worker accessed a Tk variable'
      return _original(self,*args,**kwargs)
     guards.enter_context(patch.object(cls,name,checked))
  for name in ('connect','connect_ex','bind','sendto'):
   guards.enter_context(patch.object(socket.socket,name,blocked))
  guards.enter_context(patch('subprocess.Popen',blocked))
  if hasattr(os,'startfile'): guards.enter_context(patch('os.startfile',blocked))
  guards.enter_context(patch.object(threading.Thread,'start'))
  guards.enter_context(patch.object(threading.Thread,'join'))
  guards.enter_context(patch('vector1a.app.load_settings',return_value={}))
  guards.enter_context(patch('vector1a.app.save_settings',side_effect=blocked))
  guards.enter_context(patch.object(VectorApp,'_save_settings'))
  guards.enter_context(patch('vector1a.app.FunscriptTimeline.request_media_poll'))
  for name in ('_auto_start_session','_auto_start_director','show_setup_guide'):
   guards.enter_context(patch.object(VectorApp,name))
  for model in SPATIAL_MODELS:
   variants=('generated','authored','event','suppressed','pressure')
   if extended: variants+=('matching','texture','gains','custom_focus','sequence')
   for variant in variants:
    root=tk.Tk(); root.withdraw()
    with patch.object(root,'after',return_value='disabled'):
     app=VectorApp(root)
     if worker_check:
      from dataclasses import FrozenInstanceError
      original_compose=app.output_composer.compose
      def checked_compose(sample,config,_compose=original_compose):
       result=_compose(sample,config)
       assert isinstance(result.primary_args,tuple) and isinstance(result.prostate_args,tuple)
       try: result.outgoing_volumes=(0.,0.)
       except FrozenInstanceError: pass
       else: raise AssertionError('Composition result was mutable')
       if result.primary_overrides:
        try: result.primary_overrides['V0']=0.
        except TypeError: pass
        else: raise AssertionError('Authored result overrides were mutable')
       return result
      app.output_composer.compose=checked_compose
     frames={'primary':[],'prostate':[]}
     for client,key in ((app.restim,'primary'),(app.prostate_restim,'prostate')):
      client._socket=FakeSocket(frames[key])
     for sender in (app.restim_sender,app.prostate_sender):
      guards.enter_context(patch.object(sender,'submit',side_effect=lambda fn,**kw:fn()))
     with patch('time.monotonic',return_value=10.):
      app.four_phase_spatial_model.set(model)
      app.howl_pulse.set(True)
      if variant=='matching':
       app.match_spatial_intensity.set(True)
      if variant=='texture':
       for name,value in dict(four_phase_stroke_phase_texture=True,
            four_phase_reversal_emphasis=True,four_phase_group_delay=True,
            four_phase_group_delay_ms=100.,four_phase_volume_modulation=True,
            motion_rising_volume_multiplier=.85,motion_falling_volume_multiplier=.95).items():
        getattr(app,name).set(value)
      if variant=='gains':
       for ctl,target in ((app._top_spatial_gain,1.2),(app._bottom_spatial_gain,.8)):
        ctl.set_target(target,minimum=.5,maximum=1.5,now=9.)
        ctl._last_update=9.
      if variant=='custom_focus':
       app.director_top_focus.set('Root Focus')
       app.director_bottom_focus.set('Anal Focus')
       app.top_focus_strength.set(1.5)
       app._custom_curves[0]['points'][0][1]=35.
       app._publish_output_config()
      if variant=='sequence':
       app.variety_enabled.set(True)
       app.variety_electrode_morph.set(True)
       app._variety_started=0.
       app.four_phase_moving_sequence.set(True)
       app._publish_output_config()
      app.authored_routing_mode.set('Auto authored ReStim set')
      app.director_events_enabled.set(variant=='event')
      if variant in ('authored','event'):
       for axis,value in (('V0',.22),('C0',.31),('P0',.42),('E1',.68)):
        app.axis_router.receive(TCodeCommand(axis,value,0),9.9)
      if variant=='event':
       assert app.event_engine.schedule_trigger('volume_shift',{'shift_start':.05,'shift_end':.05,'duration_ms':2000},11.)
      if variant=='suppressed':
       app.send_frequency.set(False); app.send_pulse_width.set(False)
      if variant=='pressure':
       app.pressure_control.sensor.snapshot=lambda:dict(fresh=True,pressure_kpa=23.)
       app.pressure_control.configure(app.pressure_control.settings,True)
       app.pressure_control.current=.8
      if worker_check:
       from dataclasses import FrozenInstanceError, fields
       for field in fields(app._output_config):
        if field.name not in ('custom_curves','variety_started'):
         assert getattr(app._output_config,field.name)==getattr(app,field.name).get()
       try: app._output_config.volume=.1
       except FrozenInstanceError: pass
       else: raise AssertionError('Snapshot was mutable')
       # Curve edits publish detached values immediately, without requiring Apply.
       original=app._custom_curves[0]['points'][0][1]
       previous=app._output_config
       app._custom_curves[0]['points'][0][1]=37.
       from vector1a.custom_spatial import CurveEditor
       from types import SimpleNamespace
       editor=SimpleNamespace(app=app,save_timer=None,window=SimpleNamespace(after=lambda *a:'disabled'),save=lambda:None,draw=lambda:None)
       CurveEditor.changed(editor)
       assert app._output_config.custom_curves[0]['points'][0][1]==37.
       assert previous.custom_curves[0]['points'][0][1]==original
       app._custom_curves[0]['points'][0][1]=original
       app._publish_output_config()
      sample=OutputSample(1,10.,12.,.3,.6,65.,.4,.7,.42,MotionMode.CIRCULAR,.25,.35,.45,.55,.2,.8,.33, .1,.4,1.)
      for offset in (0.,.02,.04):
       from dataclasses import replace
       current=replace(sample,calculated_at=10.+offset,due_at=12.+offset,raw_l0=.3+offset,output_l0=.6-offset)
       if worker_check:
        errors=[]
        def compose():
         try: app._send_sample(current)
         except BaseException as exc: errors.append(exc)
        worker=threading.Thread(target=compose)
        real_start(worker);real_join(worker,2.)
        assert not worker.is_alive(), 'Composition worker stalled'
        if errors: raise errors[0]
       else:
        app._send_sample(current)
      records[model+'/'+variant]=frames
     app.close()
  root=tk.Tk();root.withdraw()
  with patch.object(root,'after',return_value='disabled'):
   app=VectorApp(root); frames={'primary':[],'prostate':[]}
   for client,key in ((app.restim,'primary'),(app.prostate_restim,'prostate')):client._socket=FakeSocket(frames[key])
   for sender in (app.restim_sender,app.prostate_sender):guards.enter_context(patch.object(sender,'submit',side_effect=lambda fn,**kw:fn()))
   with patch('time.monotonic',return_value=10.):
    app.neutral();app.stop();app.resume()
   records['controls']=dict(frames=frames,state=app.engine.control_state())
   app.close()
 # Exercise real scheduling separately using an injected clock, without worker threads.
 for mode in MotionMode:
  sent=[]; now=[10.]
  engine=VectorEngine(sent.append,clock=lambda:now[0],lookahead_seconds=.1)
  engine.mode=mode;engine.resume()
  for i in range(21):
   now[0]=round(10.+i*.02,6)
   if i in (0,5,10,15):engine.receive_l0((.2,.8,.3,.7)[i//5],100,now[0])
   engine.step(now[0],now[0])
  before=len(sent);engine.stop();engine.receive_l0(.9,0,11.);engine.step(11.,11.)
  assert len(sent)==before and engine.diagnostics().state=='Stopped'
  records['scheduler/'+mode.value]=[dict(sequence=s.sequence,calculated_at=round(s.calculated_at,6),due_at=round(s.due_at,6),alpha=round(s.alpha,12),beta=round(s.beta,12),volume=round(s.volume,12)) for s in sent]
  assert sent and all(abs(s.due_at-s.calculated_at-.1)<1e-9 for s in sent)
 for model in SPATIAL_MODELS:
  assert records[model+'/authored'] != records[model+'/event'], 'Event must be active on the release timeline'
  assert 'C0' not in records[model+'/suppressed']['primary'][0]
  assert 'P1' not in records[model+'/suppressed']['prostate'][0]
  assert records[model+'/generated'] != records[model+'/pressure']
 return records

if __name__=='__main__':
 result=capture(Path(sys.argv[1]).resolve())
 Path(sys.argv[2]).write_text(json.dumps(result,indent=2,sort_keys=True),encoding='utf-8')
 print('Captured',len(result),'deterministic scenarios')
