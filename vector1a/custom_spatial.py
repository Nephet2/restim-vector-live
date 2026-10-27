"""Editable four-phase electrode curves and local Tk preview."""
from __future__ import annotations
import math
import tkinter as tk
from tkinter import ttk, messagebox
from .antialias_canvas import painter, present, ANTIALIAS_AVAILABLE
from .spatial_curves_math import evaluate, validate_curve, preset as channel_preset
from .fourphase import _constrain_restim, restim_crossfade, depth_spread

COLORS = ('#7ddfcb','#f1b095','#adadff','#ecd17e')
NAMES = ('E1 / A','E2 / B','E3 / C','E4 / D')
PRESETS = ('Moving focus','Depth spread','Staggered','Equal values')

def make_preset(name):
    xs=[0, 16.667, 33.333, 50, 66.667, 83.333, 100]
    if name == 'Equal values':
        return [{'points':[[0,50],[100,50]],'interpolation':'linear'} for _ in range(4)]
    profiles=[]
    for x in xs:
        p=x/100
        if name == 'Depth spread': vals=depth_spread(p)
        elif name == 'Staggered': vals=tuple(max(0,1-abs(p-i/3)*3) for i in range(4))
        else: vals=restim_crossfade(p,1,.30,1,'Cosine',1)
        profiles.append(vals)
    return [dict(points=[[x,round(profiles[j][i]*100,3)] for j,x in enumerate(xs)],
                 interpolation='linear' if name == 'Moving focus' else 'smooth') for i in range(4)]

def validate_curves(curves):
    if not isinstance(curves,list) or len(curves)!=4: raise ValueError('Four curves are required')
    return [validate_curve(c) for c in curves]

def validate_profile(name, description, curves):
    if not isinstance(name,str) or not name.strip() or len(name.strip())>80:
        raise ValueError('Profile name must be 1-80 characters')
    if not isinstance(description,str) or len(description)>500:
        raise ValueError('Description must be at most 500 characters')
    return name.strip(), {'description':description.strip(), 'curves':validate_curves(curves)}

def validated_profiles(data):
    if not isinstance(data,dict): return {}
    result={}
    for key,profile in data.items():
        if len(result)>=100: break
        try:
            name,value=validate_profile(key,profile.get('description',''),profile.get('curves'))
            result[name]=value
        except (ValueError,TypeError,AttributeError):
            continue
    return result

def evaluate_curves(curves, position):
    requested=tuple(evaluate(c,position) for c in curves)
    return _constrain_restim(requested)

class CurveEditor:
    def __init__(self, app):
        self.app=app; self.window=tk.Toplevel(app.root);self.window.title('Custom spatial curves')
        self.window.geometry('1050x850');self.window.configure(background='#101722')
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda e:self.close())
        self.drag=None;self.save_timer=None;self.running=True;self.yaw=-24;self.pitch=25
        top=tk.Frame(self.window,bg='#101722');top.pack(fill='x',padx=12,pady=8)
        tk.Label(top,text='Custom spatial curves  ·  E1–E4',bg='#101722',fg='#e7eef8',font=('Segoe UI',15,'bold')).pack(side='left')
        self.status=tk.StringVar(value='Select Custom in Spatial model to use these curves')
        tk.Label(top,textvariable=self.status,bg='#101722',fg='#7ddfcb').pack(side='right')
        toolbar=tk.Frame(self.window,bg='#101722');toolbar.pack(fill='x',padx=12)
        self.preset=tk.StringVar(value='Moving focus')
        ttk.Combobox(toolbar,textvariable=self.preset,values=PRESETS,state='readonly',width=18).pack(side='left')
        ttk.Button(toolbar,text='Load preset',command=self.load_preset).pack(side='left',padx=5)
        ttk.Button(toolbar,text='Use Custom spatial mode',command=self.activate).pack(side='left',padx=5)
        ttk.Label(toolbar,text='Drag points • double-click to add • right-click to remove').pack(side='left',padx=10)
        profiles=tk.Frame(self.window,bg='#1b2738',padx=10,pady=8);profiles.pack(fill='x',padx=16,pady=(8,0))
        heading=tk.Frame(profiles,bg='#1b2738');heading.pack(fill='x')
        tk.Label(heading,text='CUSTOM PROFILES',bg='#1b2738',fg='#7ddfcb',font=('Segoe UI',9,'bold')).pack(side='left')
        tk.Label(heading,text='Saved profile:',bg='#1b2738',fg='#acbed2').pack(side='left',padx=(18,4))
        self.profile_choice=tk.StringVar(value='')
        self.profile_box=ttk.Combobox(heading,textvariable=self.profile_choice,state='readonly',width=24)
        self.profile_box.pack(side='left');self.profile_box.bind('<<ComboboxSelected>>',self.select_profile)
        ttk.Button(heading,text='Load profile',command=self.load_profile).pack(side='left',padx=6)
        fields=tk.Frame(profiles,bg='#1b2738');fields.pack(fill='x',pady=(6,0))
        self.profile_name=tk.StringVar();self.profile_description=tk.StringVar()
        name_box=tk.Frame(fields,bg='#1b2738');name_box.pack(side='left',fill='x',padx=(0,8))
        tk.Label(name_box,text='Profile name',bg='#1b2738',fg='#e7eef8',anchor='w').pack(fill='x')
        self.name_entry=tk.Entry(name_box,textvariable=self.profile_name,width=20,bg='white',fg='#111d2e',insertbackground='#111d2e',relief='solid',borderwidth=1)
        self.name_entry.pack(fill='x',ipady=3)
        desc_box=tk.Frame(fields,bg='#1b2738');desc_box.pack(side='left',fill='x',expand=True,padx=(0,8))
        tk.Label(desc_box,text='Description',bg='#1b2738',fg='#e7eef8',anchor='w').pack(fill='x')
        self.description_entry=tk.Entry(desc_box,textvariable=self.profile_description,width=24,bg='white',fg='#111d2e',insertbackground='#111d2e',relief='solid',borderwidth=1)
        self.description_entry.pack(fill='x',expand=True,ipady=3)
        buttons=tk.Frame(fields,bg='#1b2738');buttons.pack(side='right',anchor='s')
        ttk.Button(buttons,text='Save profile',command=self.save_profile).pack(side='left',padx=3)
        ttk.Button(buttons,text='Update description',command=self.update_description).pack(side='left',padx=3)
        self.name_entry.bind('<Return>',lambda event:self.save_profile())
        self.description_entry.bind('<Return>',lambda event:self.save_profile())
        self.profile_status=tk.StringVar(value='Type a profile name and description, then click Save profile.')
        tk.Label(profiles,textvariable=self.profile_status,bg='#1b2738',fg='#acbed2',anchor='w').pack(fill='x',pady=(3,0))
        self.refresh_profiles()
        grid=tk.Frame(self.window,bg='#101722');grid.pack(fill='x',padx=12,pady=8)
        self.plots=[];self.modes=[]
        for i in range(4):
            card=tk.Frame(grid,bg='#1b2738',padx=8,pady=5);card.grid(row=i//2,column=i%2,sticky='nsew',padx=4,pady=4)
            head=tk.Frame(card,bg='#1b2738');head.pack(fill='x')
            tk.Label(head,text=NAMES[i],fg=COLORS[i],bg='#1b2738',font=('Segoe UI',11,'bold')).pack(side='left')
            mode=tk.StringVar(value=self.app._custom_curves[i]['interpolation']);self.modes.append(mode)
            shape=tk.StringVar(value='Shape...')
            shapes=('flat','rising','falling','triangle','bell','valley','crossover_1','crossover_2')
            shape_menu=ttk.Combobox(head,textvariable=shape,values=shapes,state='readonly',width=12);shape_menu.pack(side='right',padx=5)
            shape_menu.bind('<<ComboboxSelected>>',lambda e,n=i,v=shape:self.change_shape(n,v))
            menu=ttk.Combobox(head,textvariable=mode,values=('smooth','linear'),state='readonly',width=9);menu.pack(side='right')
            menu.bind('<<ComboboxSelected>>',lambda e,n=i:self.change_mode(n))
            canvas=tk.Canvas(card,width=450,height=152,background='#121d2c',highlightthickness=0);canvas.pack(fill='x',expand=True)
            canvas.bind('<ButtonPress-1>',lambda e,n=i:self.press(e,n));canvas.bind('<B1-Motion>',lambda e,n=i:self.move(e,n))
            canvas.bind('<ButtonRelease-1>',lambda e:self.release());canvas.bind('<Double-Button-1>',lambda e,n=i:self.add(e,n))
            canvas.bind('<Button-3>',lambda e,n=i:self.remove(e,n));self.plots.append(canvas)
        grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
        info=tk.Label(self.window,text='Curves are requested logical electrode values. ReStim constraints, electrode order, focus or authored E axes may change transmitted E1–E4. Volume remains separate.',bg='#101722',fg='#acbed2',wraplength=1000,justify='left')
        info.pack(anchor='w',padx=15)
        three_head=tk.Frame(self.window,bg='#101722');three_head.pack(fill='x',padx=16)
        tk.Label(three_head,text='3D CURVE OVERVIEW',bg='#101722',fg='#7ddfcb',font=('Segoe UI',9,'bold')).pack(side='left')
        ttk.Button(three_head,text='Reset view',command=self.reset_view).pack(side='right')
        self.three=tk.Canvas(self.window,height=300,bg='#121d2c',highlightthickness=0);self.three.pack(fill='both',expand=True,padx=16,pady=8)
        self.three.bind('<ButtonPress-1>',self.rot_start);self.three.bind('<B1-Motion>',self.rot_move)
        self.window.after(100,self.refresh)
    def refresh_profiles(self):
        self.profile_box['values']=sorted(self.app._custom_profiles, key=str.casefold)
    def select_profile(self,event=None):
        name=self.profile_choice.get();profile=self.app._custom_profiles.get(name)
        if profile:
            self.profile_name.set(name);self.profile_description.set(profile['description'])
            self.profile_status.set('Selected: '+name+' - Load applies it; Save profile replaces its curves.')
    def save_profile(self):
        try:
            name=self.app.save_custom_profile(self.profile_name.get(),self.profile_description.get())
        except (ValueError,OSError) as e:
            messagebox.showerror('Custom profile',str(e),parent=self.window);return
        self.profile_choice.set(name);self.profile_name.set(name);self.refresh_profiles()
        self.profile_status.set('Saved: '+name)
    def update_description(self):
        name=self.profile_choice.get()
        try:self.app.update_custom_profile_description(name,self.profile_description.get())
        except (ValueError,OSError) as e:
            messagebox.showerror('Custom profile',str(e),parent=self.window);return
        self.profile_status.set('Description updated: '+name)
    def load_profile(self):
        name=self.profile_choice.get()
        try:self.app.apply_custom_profile(name)
        except (ValueError,OSError) as e:
            messagebox.showerror('Custom profile',str(e),parent=self.window);return
        self.sync_loaded_profile(name)
    def sync_loaded_profile(self,name):
        self.refresh_profiles();self.profile_choice.set(name);self.select_profile()
        for i,c in enumerate(self.app._custom_curves):self.modes[i].set(c['interpolation'])
        self.profile_status.set('Loaded: '+name+' - Custom spatial mode active')
        self.draw()
    def close(self):
        self.running=False
        if self.save_timer:
            self.window.after_cancel(self.save_timer);self.save_timer=None;self.app._save_settings()
        self.window.destroy();self.app._custom_curve_editor=None
    def activate(self):
        self.app.four_phase_spatial_model.set('Custom');self.app.apply_config();self.app._save_settings()
    def load_preset(self):
        self.app._custom_curves=validate_curves(make_preset(self.preset.get()))
        for i,c in enumerate(self.app._custom_curves):self.modes[i].set(c['interpolation'])
        self.changed()
    def change_shape(self,i,variable):
        curves=validate_curves(self.app._custom_curves)
        curves[i]=channel_preset(variable.get(),curves[i]['interpolation'])
        self.app._custom_curves=validate_curves(curves);variable.set('Shape...');self.changed()
    def change_mode(self,i):
        curves=validate_curves(self.app._custom_curves);curves[i]['interpolation']=self.modes[i].get()
        self.app._custom_curves=validate_curves(curves);self.changed()
    def changed(self):
        if self.save_timer:self.window.after_cancel(self.save_timer)
        self.save_timer=self.window.after(300,self.save)
        self.draw()
    def save(self):
        self.save_timer=None;self.app._save_settings()
    def coords(self,c,x,y):
        w=max(100,c.winfo_width());h=max(100,c.winfo_height())
        return 30+x*(w-45)/100, 8+(100-y)*(h-28)/100
    def data(self,c,event):
        w=max(100,c.winfo_width());h=max(100,c.winfo_height())
        return max(0,min(100,(event.x-30)*100/(w-45))), max(0,min(100,100-(event.y-8)*100/(h-28)))
    def closest(self,event,i):
        c=self.plots[i];pts=self.app._custom_curves[i]['points']
        distances=[(math.hypot(event.x-self.coords(c,*p)[0],event.y-self.coords(c,*p)[1]),j) for j,p in enumerate(pts)]
        dist,j=min(distances);return j if dist<=12 else None
    def press(self,event,i):
        j=self.closest(event,i);self.drag=(i,j) if j is not None else None
    def release(self):self.drag=None
    def move(self,event,i):
        if not self.drag or self.drag[0]!=i:return
        j=self.drag[1];curves=validate_curves(self.app._custom_curves);pts=curves[i]['points'];x,y=self.data(self.plots[i],event)
        x=pts[j][0] if j in (0,len(pts)-1) else max(pts[j-1][0]+.1,min(pts[j+1][0]-.1,x))
        pts[j]=[round(x,3),round(y,2)];self.app._custom_curves=validate_curves(curves);self.changed()
    def add(self,event,i):
        if self.closest(event,i) is not None:return
        curves=validate_curves(self.app._custom_curves);pts=curves[i]['points'];x,y=self.data(self.plots[i],event)
        if len(pts)>=24 or any(abs(x-p[0])<.1 for p in pts):return
        pts.append([round(x,3),round(y,2)]);pts.sort(key=lambda p:p[0]);self.app._custom_curves=validate_curves(curves);self.changed()
    def remove(self,event,i):
        j=self.closest(event,i);curves=validate_curves(self.app._custom_curves);pts=curves[i]['points']
        if j is None or j in (0,len(pts)-1):return
        del pts[j];self.app._custom_curves=validate_curves(curves);self.changed()
    def reset_view(self):
        self.yaw=-24;self.pitch=25;self.draw_3d()
    def rot_start(self,e):self._last=(e.x,e.y)
    def rot_move(self,e):
        dx=e.x-self._last[0];dy=e.y-self._last[1];self._last=(e.x,e.y)
        self.yaw=max(-75,min(75,self.yaw+dx*.5));self.pitch=max(10,min(70,self.pitch+dy*.4));self.draw_3d()
    def refresh(self):
        if not self.running:return
        self.status.set('CUSTOM ACTIVE' if self.app.four_phase_spatial_model.get()=='Custom' else 'Preview • select Custom to use')
        self.draw();self.window.after(150,self.refresh)
    def draw(self):
        pos=max(0,min(1,self.app._four_phase_send_last_l0));curves=self.app._custom_curves
        # Skip five expensive supersampled redraws when nothing visible changed.
        signature=(pos,repr(curves),self.yaw,self.pitch,
                   tuple((c.winfo_width(),c.winfo_height())
                         for c in (*self.plots,self.three)))
        if signature == getattr(self,'_draw_signature',None):return
        self._draw_signature=signature
        for i,canvas in enumerate(self.plots):
            c=painter(canvas)
            c.delete('all');w=max(100,c.winfo_width());h=max(100,c.winfo_height())
            for value in (0,25,50,75,100):
                x,_=self.coords(c,value,0);_,y=self.coords(c,0,value)
                c.create_line(x,8,x,h-20,fill='#304158');c.create_line(30,y,w-15,y,fill='#304158')
                c.create_text(25,y,text=str(value),fill='#acbed2',anchor='e',font=('Segoe UI',8))
                c.create_text(x,h-9,text=str(value),fill='#acbed2',font=('Segoe UI',8))
            xy=[]
            for n in range(101):xy.extend(self.coords(c,n,evaluate(curves[i],n/100)*100))
            c.create_line(*xy,fill=COLORS[i],width=2)
            x,y=self.coords(c,pos*100,evaluate(curves[i],pos)*100);c.create_line(x,8,x,h-20,fill=COLORS[i],dash=(3,4));c.create_oval(x-5,y-5,x+5,y+5,fill=COLORS[i],outline='white')
            for px,py in curves[i]['points']:
                x,y=self.coords(c,px,py);c.create_oval(x-5,y-5,x+5,y+5,fill=COLORS[i],outline='#101722',width=2)
            present(c)
        self.draw_3d()
    def draw_3d(self):
        c=painter(self.three);c.delete('all');w=max(250,c.winfo_width());h=max(150,c.winfo_height())
        yaw=math.radians(self.yaw);pitch=math.radians(self.pitch)
        def raw(x,y,z):
            u=x*math.cos(yaw)+z*math.sin(yaw);v=-x*math.sin(yaw)+z*math.cos(yaw)
            return u,-y*math.cos(pitch)+v*math.sin(pitch),y*math.sin(pitch)+v*math.cos(pitch)
        corners=[raw(x,y,z) for x in (-1.2,1.2) for y in (0,1.1) for z in (-1,1)]
        minx,maxx=min(p[0] for p in corners),max(p[0] for p in corners)
        miny,maxy=min(p[1] for p in corners),max(p[1] for p in corners)
        scale=1.3*min((w*.80)/(maxx-minx),(h*.75)/(maxy-miny))
        def xyz(x,y,i):
            p=raw((x-.5)*2.4,y*1.1,(1.5-i)*.56)
            return (w*.5+(p[0]-(minx+maxx)/2)*scale,
                    h*.49+(p[1]-(miny+maxy)/2)*scale,p[2])
        def line(a,b,color='#43566d',**kwargs):c.create_line(*a[:2],*b[:2],fill=color,**kwargs)
        def blended(color,alpha=.28):
            fg=[int(color[i:i+2],16) for i in (1,3,5)];bg=[0x12,0x1d,0x2c]
            return '#'+''.join('%02x'%round(b*(1-alpha)+f*alpha) for f,b in zip(fg,bg))
        for n in range(5):
            x=n/4;a,b=xyz(x,0,0),xyz(x,0,3);line(a,b)
            c.create_text(a[0],a[1]+15,text=str(n*25)+'%',fill='#acbed2',font=('Segoe UI',9))
        for i in range(4):
            a,b=xyz(0,0,i),xyz(1,0,i);line(a,b)
            c.create_text(b[0]+18,b[1],text='E'+str(i+1),fill=COLORS[i],font=('Segoe UI',9,'bold'))
        line(xyz(0,0,0),xyz(0,1,0))
        for y in (.5,1):
            v=xyz(-.07,y,0);c.create_text(v[0]-5,v[1],text=str(round(y*100))+'%',fill='#acbed2',font=('Segoe UI',9))
        pos=max(0,min(1,self.app._four_phase_send_last_l0))
        plane=[xyz(pos,0,0),xyz(pos,1,0),xyz(pos,1,3),xyz(pos,0,3)]
        c.create_polygon(*[v for p in plane for v in p[:2]],fill='#263447',outline='#64758a',dash=(4,5))
        curves=self.app._custom_curves;faces=[]
        for i in range(4):
            for n in range(60):
                a=n/60;b=(n+1)/60
                pts=[xyz(a,0,i),xyz(a,evaluate(curves[i],a),i),xyz(b,evaluate(curves[i],b),i),xyz(b,0,i)]
                faces.append((sum(p[2] for p in pts)/4,i,pts))
        for _,i,pts in sorted(faces,key=lambda item:item[0]):
            c.create_polygon(*[v for p in pts for v in p[:2]],fill=blended(COLORS[i]),outline='')
        for i in sorted(range(4),key=lambda j:xyz(.5,.5,j)[2]):
            xy=[]
            for n in range(121):
                x=n/120;p=xyz(x,evaluate(curves[i],x),i);xy.extend(p[:2])
            c.create_line(*xy,fill=COLORS[i],width=2)
            point=xyz(pos,evaluate(curves[i],pos),i);line(xyz(pos,0,i),point,COLORS[i],dash=(3,3))
            c.create_oval(point[0]-5,point[1]-5,point[0]+5,point[1]+5,fill=COLORS[i],outline='white')
            c.create_text(point[0],point[1]-13,text='E%d %.0f%%'%(i+1,evaluate(curves[i],pos)*100),fill=COLORS[i],font=('Segoe UI',9,'bold'))
        c.create_text(12,h-10,anchor='sw',text='Position  |  Depth: electrode  |  Height: requested value   -   Drag to rotate',fill='#acbed2',font=('Segoe UI',9))
        present(c)
