"""Fixed-clock tempo scenarios shared by reference capture and regression tests."""
class Timeline:
 def __init__(self): self.position=4.;self.missing_sample=False
 def position_seconds(self): return self.position
 def sample_position(self,seconds):
  if self.missing_sample:return None
  p=seconds%2.
  return p if p<=1 else 2-p

def tempo_trace(factory):
 result={}
 for name,scale,transition in [('double',2.,.2),('half',.5,.2),('instant',2.,0.),('long_blend',.5,5.),('missing_media',2.,.2),('missing_sample',2.,.2),('manual_restore',2.,.2),('restart',.5,.2)]:
  timeline=Timeline();ctl=factory(timeline)
  ctl.start(scale,4.,10.,1.,transition)
  rows=[]
  for i,now in enumerate((10.,10.1,10.2,10.8,11.,11.1,11.2,11.5,14.)):
   timeline.position=4.+now-10.
   if name=='missing_media' and i in (2,3):timeline.position=None
   if name=='missing_sample':timeline.missing_sample=i in (2,3)
   if name=='manual_restore' and i==3:ctl.restore(now)
   if name=='restart' and i==5:ctl.start(2.,timeline.position,now,1.,.2)
   raw=(-.2,.25,.5,.75,1.2,.6,.2,.8,.4)[i]
   rows.append([now,ctl.transform(raw,now),ctl.scale])
  result[name]=rows
 return result


def input_trace(factory):
 from types import SimpleNamespace
 from vector1a.engine import VectorEngine
 now=[10.];sent=[];observed=[]
 engine=VectorEngine(sent.append,clock=lambda:now[0],lookahead_seconds=.1)
 timeline=Timeline()
 timeline.observe_live=lambda value,at:observed.append([value,at])
 generated=SimpleNamespace(active=False,stroke_bounds=lambda at:(.2,.8))
 ctl=factory(engine,timeline,generated)
 engine.resume()
 for i in range(31):
  now[0]=round(10.+i*.02,6);timeline.position=4.+i*.02
  if i in (0,5,10,15,20,25,30):ctl.receive_authored((i%9)/10.,100,now[0])
  if i==10:generated.active=True
  if 10<=i<20:ctl.receive_generated(.2+(i-10)*.06,20,now[0])
  if i==20:generated.active=False
  if i==25:engine.stop()
  if i==28:engine.resume()
  engine.step(now[0],now[0])
 return dict(observed=observed,samples=[dict(sequence=s.sequence,calculated_at=s.calculated_at,due_at=s.due_at,raw=s.raw_l0,output=s.output_l0,alpha=s.alpha,beta=s.beta,volume=s.volume) for s in sent],state=engine.control_state())
