"""Supersampled Tk canvas drawing for the Custom curves preview."""
from __future__ import annotations
import math
from pathlib import Path
import sys

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    vendor = Path(__file__).resolve().parent / '_vendor' / ('cp%d%d' % sys.version_info[:2])
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    try:
        from PIL import Image, ImageDraw, ImageTk
    except ImportError:
        Image = ImageDraw = ImageTk = None

ANTIALIAS_AVAILABLE = Image is not None

class SmoothCanvas:
    """Rasterise shapes at twice display resolution; keep native crisp Tk labels."""
    def __init__(self, canvas, scale=2):
        self.canvas=canvas;self.scale=scale;self.labels=[]
        self.w=max(100,canvas.winfo_width());self.h=max(100,canvas.winfo_height())
        bg=canvas.cget('background')
        self.img=Image.new('RGB',(self.w*scale,self.h*scale),bg)
        self.pen=ImageDraw.Draw(self.img)
    def winfo_width(self):return self.w
    def winfo_height(self):return self.h
    def delete(self,*args):pass
    def points(self,coords):return [(round(coords[i]*self.scale),round(coords[i+1]*self.scale)) for i in range(0,len(coords),2)]
    def create_line(self,*coords,**options):
        pts=self.points(coords);fill=options.get('fill','#ffffff');width=max(1,round(options.get('width',1)*self.scale))
        dash=options.get('dash')
        if not dash:
            self.pen.line(pts,fill=fill,width=width,joint='curve');return
        pattern=[max(1,x*self.scale) for x in dash];stage=0;remaining=pattern[0];on=True
        for a,b in zip(pts,pts[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1];distance=math.hypot(dx,dy)
            if distance<=0:continue
            at=0
            while at<distance:
                step=min(remaining,distance-at)
                if on:self.pen.line([(a[0]+dx*at/distance,a[1]+dy*at/distance),(a[0]+dx*(at+step)/distance,a[1]+dy*(at+step)/distance)],fill=fill,width=width)
                at+=step;remaining-=step
                if remaining<=1e-9:stage=(stage+1)%len(pattern);remaining=pattern[stage];on=not on
    def create_polygon(self,*coords,**options):
        pts=self.points(coords);fill=options.get('fill') or None;outline=options.get('outline') or None
        self.pen.polygon(pts,fill=fill)
        if outline:self.pen.line(pts+[pts[0]],fill=outline,width=self.scale,joint='curve')
    def create_oval(self,*coords,**options):
        box=tuple(round(v*self.scale) for v in coords);width=max(1,round(options.get('width',1)*self.scale))
        self.pen.ellipse(box,fill=options.get('fill') or None,outline=options.get('outline') or None,width=width)
    def create_text(self,*coords,**options):self.labels.append((coords,options))
    def commit(self):
        resampling=getattr(Image,'Resampling',Image)
        image=self.img.resize((self.w,self.h),resampling.LANCZOS)
        self.canvas.delete('all');self.canvas._antialias_image=ImageTk.PhotoImage(image,master=self.canvas)
        self.canvas.create_image(0,0,image=self.canvas._antialias_image,anchor='nw')
        for coords,options in self.labels:self.canvas.create_text(*coords,**options)

def painter(canvas):
    return SmoothCanvas(canvas) if ANTIALIAS_AVAILABLE else canvas

def present(paint):
    if isinstance(paint,SmoothCanvas):paint.commit()
