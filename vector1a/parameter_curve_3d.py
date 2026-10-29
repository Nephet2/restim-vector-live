"""Rotatable lane composite; each parameter retains its own input marker."""
import math
from .antialias_canvas import painter, present
from .parameter_curves import PARAMETERS
from .spatial_curves_math import evaluate


class ParameterCurveComposite:
    def __init__(self, canvas):
        self.canvas = canvas
        self.yaw, self.pitch = -28., 25.
        self.last_pointer = None
        self.curves, self.snapshot = None, {}
        canvas.bind('<ButtonPress-1>', self.press)
        canvas.bind('<B1-Motion>', self.move)
        canvas.bind('<Configure>', lambda event: self.draw())

    def press(self, event):
        self.last_pointer = event.x, event.y

    def move(self, event):
        if self.last_pointer is None:
            return
        x,y = self.last_pointer
        self.yaw = (self.yaw + (event.x-x)*.5) % 360
        self.pitch = min(75., max(10., self.pitch + (event.y-y)*.4))
        self.last_pointer = event.x,event.y
        self.draw()

    def reset(self):
        self.yaw, self.pitch = -28., 25.
        self.last_pointer = None
        self.draw()

    def update(self, curves, snapshot):
        self.curves, self.snapshot = curves, snapshot
        self.draw()

    def projector(self, width, height):
        yaw,pitch = math.radians(self.yaw),math.radians(self.pitch)
        def raw(x,y,lane):
            x,y,z = (x-.5)*2.2, (y-.5)*1.2, (lane-(len(PARAMETERS)-1)/2)*.46
            horizontal = x*math.cos(yaw)+z*math.sin(yaw)
            depth = -x*math.sin(yaw)+z*math.cos(yaw)
            return horizontal,-y*math.cos(pitch)+depth*math.sin(pitch),y*math.sin(pitch)+depth*math.cos(pitch)
        corners=[raw(x,y,lane) for x in (0,1) for y in (0,1) for lane in (0,len(PARAMETERS)-1)]
        xmin,xmax=min(p[0] for p in corners),max(p[0] for p in corners)
        ymin,ymax=min(p[1] for p in corners),max(p[1] for p in corners)
        scale=min(max(40,width-105)/(xmax-xmin),max(40,height-100)/(ymax-ymin))
        def point(x,y,lane):
            px,py,depth=raw(x,y,lane)
            return width/2+(px-(xmin+xmax)/2)*scale,height/2+(py-(ymin+ymax)/2)*scale,depth
        return point

    def draw(self):
        if self.curves is None:
            return
        width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
        signature=(repr(self.curves),repr(self.snapshot),self.yaw,self.pitch,width,height)
        if signature==getattr(self,'signature',None):return
        self.signature=signature
        c=painter(self.canvas);c.delete('all')
        xyz=self.projector(width,height)
        def line(a,b,color='#40536b',**kwargs):
            c.create_line(*a[:2],*b[:2],fill=color,**kwargs)
        for n in range(5):
            x=n/4
            a,b=xyz(x,0,0),xyz(x,0,len(PARAMETERS)-1)
            line(a,b)
            c.create_text(a[0],a[1]+14,text=f'{n*25}%',fill='#acbed2',font=('Segoe UI',8))
        for lane,(_,_,axis,color) in enumerate(PARAMETERS):
            a,b=xyz(0,0,lane),xyz(1,0,lane)
            line(a,b)
            c.create_text(b[0]+12,b[1],text=axis,fill=color,font=('Segoe UI',9,'bold'),anchor='w')
        line(xyz(0,0,0),xyz(0,1,0))
        for value in (.5,1):
            a=xyz(0,value,0)
            c.create_text(a[0]-8,a[1],text=f'{value*100:.0f}%',fill='#acbed2',anchor='e',font=('Segoe UI',8))
        faces=[]
        for lane,(key,_,_,color) in enumerate(PARAMETERS):
            rgb=[int(color[i:i+2],16) for i in (1,3,5)]
            fill='#'+''.join(f'{round(b*.75+v*.25):02x}' for b,v in zip((18,29,44),rgb))
            for n in range(40):
                a,b=n/40,(n+1)/40
                points=[xyz(a,0,lane),xyz(a,evaluate(self.curves[key],a),lane),
                        xyz(b,evaluate(self.curves[key],b),lane),xyz(b,0,lane)]
                faces.append((sum(p[2] for p in points)/4,points,fill))
        for _,points,fill in sorted(faces,key=lambda face:face[0]):
            c.create_polygon(*[v for p in points for v in p[:2]],fill=fill,outline='')
        for lane in sorted(range(len(PARAMETERS)),key=lambda i:xyz(.5,.5,i)[2]):
            key,_,_,color=PARAMETERS[lane]
            coords=[v for n in range(121) for v in xyz(n/120,evaluate(self.curves[key],n/120),lane)[:2]]
            c.create_line(*coords,fill=color,width=2)
            for x,y in self.curves[key]['points']:
                px,py,_=xyz(x/100,y/100,lane)
                c.create_oval(px-3,py-3,px+3,py+3,fill=color,outline='#121d2c')
            live=self.snapshot.get(key)
            if live:
                drive=live[0]
                point=xyz(drive,evaluate(self.curves[key],drive),lane)
                line(xyz(drive,0,lane),point,color,dash=(3,3))
                c.create_oval(point[0]-5,point[1]-5,point[0]+5,point[1]+5,fill=color,outline='white',width=2)
        present(c)
