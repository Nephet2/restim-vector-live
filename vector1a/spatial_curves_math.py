"""Bounded shape-preserving curves, with percentage coordinates."""
import math
PRESETS={
 'flat':[[0,100],[100,100]],'rising':[[0,0],[100,100]],
 'falling':[[0,100],[100,0]],'triangle':[[0,0],[50,100],[100,0]],
 'bell':[[0,0],[25,20],[50,100],[75,20],[100,0]],
 'valley':[[0,100],[50,0],[100,100]],
 'crossover_1':[[0,100],[40,100],[60,0],[100,0]],
 'crossover_2':[[0,0],[40,0],[60,100],[100,100]]}
def preset(name,interpolation='smooth'):
 return dict(points=[p[:] for p in PRESETS[name]],interpolation=interpolation)
def validate_curve(data):
 if not isinstance(data,dict) or data.get('interpolation') not in ('linear','smooth'):
  raise ValueError('Curve interpolation must be linear or smooth')
 points=data.get('points');result=[]
 if not isinstance(points,list) or not 2<=len(points)<=24:raise ValueError('Curve needs 2-24 points')
 for p in points:
  if not isinstance(p,list) or len(p)!=2 or any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=100 for v in p):raise ValueError('Curve points must be finite percentages')
  if result and p[0]-result[-1][0]<.1-1e-9:raise ValueError('Curve positions must increase by at least 0.1%')
  result.append(p[:])
 if result[0][0]!=0 or result[-1][0]!=100:raise ValueError('Curve needs endpoints at 0 and 100%')
 return dict(points=result,interpolation=data['interpolation'])
def tangents(p):
 h=[b[0]-a[0] for a,b in zip(p,p[1:])]
 d=[(b[1]-a[1])/v for a,b,v in zip(p,p[1:],h)]
 if len(d)==1:return [d[0],d[0]]
 def end(h0,h1,d0,d1):
  m=((2*h0+h1)*d0-h0*d1)/(h0+h1)
  if m*d0<=0:return 0.
  return math.copysign(min(abs(m),3*abs(d0)),m) if d0*d1<=0 else m
 m=[end(h[0],h[1],d[0],d[1])]
 for i in range(1,len(p)-1):
  if d[i-1]*d[i]<=0:m.append(0.)
  else:
   w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1]
   m.append((w1+w2)/(w1/d[i-1]+w2/d[i]))
 return m+[end(h[-1],h[-2],d[-1],d[-2])]
def evaluate(curve,position):
 p=curve['points'];x=max(0,min(100,position*100))
 k=next((i for i in range(len(p)-1) if x<=p[i+1][0]),len(p)-2)
 a,b=p[k:k+2];h=b[0]-a[0];t=(x-a[0])/h
 if curve['interpolation']=='linear':y=a[1]+t*(b[1]-a[1])
 else:
  m=tangents(p)
  y=(2*t**3-3*t*t+1)*a[1]+(t**3-2*t*t+t)*h*m[k]+(-2*t**3+3*t*t)*b[1]+(t**3-t*t)*h*m[k+1]
 return max(min(a[1],b[1]),min(max(a[1],b[1]),y))/100
