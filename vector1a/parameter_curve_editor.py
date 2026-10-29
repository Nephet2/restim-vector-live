"""Live Tk parameter editor with spatial-editor point interactions."""
import math
import tkinter as tk
from tkinter import ttk, messagebox
from .antialias_canvas import painter, present
from .parameter_curves import PARAMETERS, validate_parameter_curves
from .parameter_curve_3d import ParameterCurveComposite
from .spatial_curves_math import evaluate, preset

BG, CARD, PLOT, TEXT, MUTED = '#101722', '#1b2738', '#121d2c', '#e7eef8', '#acbed2'


class ParameterCurveEditor:
    def __init__(self, app):
        self.app = app
        self.draft = validate_parameter_curves(app._parameter_curves)
        self.drag = None
        self.opening_curves = validate_parameter_curves(self.draft)
        self.save_timer = None
        self.window = tk.Toplevel(app.root)
        self.window.title('Parameter response curves')
        self.window.geometry('1360x850')
        self.window.minsize(1120, 740)
        self.window.configure(bg=BG)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda e: self.close())
        self.timer = None
        top = tk.Frame(self.window, bg=BG)
        top.pack(fill='x', padx=20, pady=(16, 6))
        tk.Label(top, text='Parameter response curves', bg=BG, fg=TEXT,
                 font=('Segoe UI', 18, 'bold')).pack(side='left')
        self.status = tk.StringVar(value='LIVE EDITING - changes apply immediately')
        tk.Label(top, textvariable=self.status, bg=BG, fg='#7ddfcb').pack(side='right')
        tk.Label(self.window, text='Double-click to add a point  |  Drag to reshape  |  Right-click an interior point to remove',
                 bg=BG, fg=MUTED, anchor='w').pack(fill='x', padx=20, pady=(0, 8))
        profiles = tk.Frame(self.window, bg=CARD, padx=12, pady=8)
        profiles.pack(fill='x', padx=20, pady=(0,8))
        row = tk.Frame(profiles, bg=CARD);row.pack(fill='x')
        tk.Label(row, text='CUSTOM PROFILES', bg=CARD, fg='#7ddfcb', font=('Segoe UI',9,'bold')).pack(side='left')
        self.profile_choice = tk.StringVar()
        self.profile_box = ttk.Combobox(row, textvariable=self.profile_choice, state='readonly', width=24)
        self.profile_box.pack(side='left', padx=(12,6))
        self.profile_box.bind('<<ComboboxSelected>>',self.select_profile)
        ttk.Button(row,text='Load profile',command=self.load_profile).pack(side='left')
        self.profile_status=tk.StringVar(value='Profiles save all six shapes; Min/Max ranges stay unchanged.')
        tk.Label(row,textvariable=self.profile_status,bg=CARD,fg=MUTED).pack(side='left',padx=12)
        row=tk.Frame(profiles,bg=CARD);row.pack(fill='x',pady=(6,0))
        self.profile_name,self.profile_description=tk.StringVar(),tk.StringVar()
        tk.Label(row,text='Name',bg=CARD,fg=TEXT).pack(side='left')
        name_entry=ttk.Entry(row,textvariable=self.profile_name,width=24);name_entry.pack(side='left',padx=(6,12))
        tk.Label(row,text='Description',bg=CARD,fg=TEXT).pack(side='left')
        desc_entry=ttk.Entry(row,textvariable=self.profile_description);desc_entry.pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(row,text='Save profile',command=self.save_profile).pack(side='left',padx=6)
        ttk.Button(row,text='Update description',command=self.update_description).pack(side='left')
        name_entry.bind('<Return>',lambda event:self.save_profile())
        self.refresh_profiles()
        self.panes=ttk.Panedwindow(self.window,orient='horizontal')
        self.panes.pack(fill='both',expand=True,padx=14)
        graph_panel = tk.Frame(self.panes,bg=BG)
        graph_panel.columnconfigure(0,weight=1);graph_panel.rowconfigure(0,weight=1)
        self.graph_canvas = tk.Canvas(graph_panel,width=840,bg=BG,highlightthickness=0,yscrollincrement=20)
        self.graph_canvas.grid(row=0,column=0,sticky='nsew')
        graph_scroll = ttk.Scrollbar(graph_panel,orient='vertical',command=self.graph_canvas.yview)
        graph_scroll.grid(row=0,column=1,sticky='ns')
        self.graph_canvas.configure(yscrollcommand=graph_scroll.set)
        grid = tk.Frame(self.graph_canvas, bg=BG)
        self.graph_grid=grid
        window_id=self.graph_canvas.create_window(0,0,anchor='nw',window=grid)
        grid.bind('<Configure>',lambda event:self.graph_canvas.configure(scrollregion=self.graph_canvas.bbox('all')))
        self.graph_canvas.bind('<Configure>',lambda event:self.graph_canvas.itemconfigure(window_id,width=event.width))
        self.window.bind('<MouseWheel>',self.scroll_graphs,add='+')
        self.panes.add(graph_panel,weight=3)
        composite_panel=tk.Frame(self.panes,bg=CARD,padx=12,pady=10)
        self.panes.add(composite_panel,weight=2)
        heading=tk.Frame(composite_panel,bg=CARD);heading.pack(fill='x')
        tk.Label(heading,text='3D RESPONSE COMPOSITE',bg=CARD,fg='#7ddfcb',font=('Segoe UI',10,'bold')).pack(side='left')
        self.three=tk.Canvas(composite_panel,width=380,height=380,bg=PLOT,highlightthickness=0)
        self.composite=ParameterCurveComposite(self.three)
        ttk.Button(heading,text='Reset view',command=self.composite.reset).pack(side='right')
        tk.Label(composite_panel,text='Drag to rotate - each colour is a parameter lane',bg=CARD,fg=MUTED,anchor='w').pack(fill='x',pady=(8,4))
        self.three.pack(fill='both',expand=True)
        details=tk.Frame(composite_panel,bg=CARD)
        details.pack(side='bottom',fill='x',before=self.three)
        for key,title,axis,color in PARAMETERS:
            tk.Label(details,text=f'{axis}  {title}',bg=CARD,fg=color,anchor='w').pack(fill='x',pady=1)
        tk.Label(details,text='X: calculated input   |   Height: response within range\nVolume lanes are before ceiling / base volume. Each lane has its own marker.',
                 bg=CARD,fg=MUTED,justify='left',wraplength=400).pack(fill='x',pady=(8,0))
        grid.columnconfigure((0, 1), weight=1, uniform='graphs')
        grid.rowconfigure(tuple(range((len(PARAMETERS)+1)//2)), weight=1, uniform='graphs')
        self.plots, self.modes, self.values, self.cards = {}, {}, {}, {}
        for index, (key, title, axis, color) in enumerate(PARAMETERS):
            card = tk.Frame(grid, bg=CARD, padx=12, pady=10)
            card.grid(row=index//2, column=index%2, sticky='nsew', padx=6, pady=6)
            self.cards[key]=card
            head = tk.Frame(card, bg=CARD)
            head.pack(fill='x')
            tk.Label(head, text=f'{title}  /  {axis}', bg=CARD, fg=color,
                     font=('Segoe UI', 11, 'bold')).pack(side='left')
            tools=tk.Frame(card,bg=CARD)
            tools.pack(fill='x',pady=(4,0))
            mode = tk.StringVar(value=self.draft[key]['interpolation'])
            self.modes[key] = mode
            menu = ttk.Combobox(tools, textvariable=mode, values=('linear', 'smooth'), state='readonly', width=8)
            menu.pack(side='right')
            menu.bind('<<ComboboxSelected>>', lambda e, k=key: self.change_mode(k))
            shape = tk.StringVar(value='Shape...')
            choices = ttk.Combobox(tools, textvariable=shape,
                                  values=('rising', 'falling', 'triangle', 'bell', 'valley', 'flat'),
                                  state='readonly', width=10)
            choices.pack(side='right', padx=6)
            choices.bind('<<ComboboxSelected>>', lambda e, k=key, v=shape: self.change_shape(k, v))
            canvas = tk.Canvas(card, width=340, height=160, bg=PLOT, highlightthickness=0)
            canvas.pack(fill='both', expand=True, pady=(10, 4))
            self.plots[key] = canvas
            canvas.bind('<Configure>', lambda e: self.draw())
            canvas.bind('<ButtonPress-1>', lambda e, k=key: self.press(e, k))
            canvas.bind('<B1-Motion>', lambda e, k=key: self.move(e, k))
            canvas.bind('<ButtonRelease-1>', lambda e: self.release())
            canvas.bind('<Double-Button-1>', lambda e, k=key: self.add(e, k))
            canvas.bind('<Button-3>', lambda e, k=key: self.remove(e, k))
            value = tk.StringVar(value='Waiting for a generated sample')
            self.values[key] = value
            tk.Label(card, textvariable=value, bg=CARD, fg=MUTED, anchor='w').pack(fill='x')
        bottom = tk.Frame(self.window,bg=BG)
        bottom.pack(side='bottom',fill='x',before=self.panes)
        self.footer = bottom
        footer = tk.Frame(bottom, bg=BG)
        footer.pack(fill='x', padx=20, pady=(10, 4))
        ttk.Button(footer, text='Reset all to straight', command=self.reset).pack(side='left')
        ttk.Button(footer, text='Restore opening curves', command=self.discard).pack(side='left', padx=8)
        ttk.Button(footer, text='Close', command=self.close).pack(side='right')
        tk.Label(bottom, bg=BG, fg=MUTED, justify='left', anchor='w',
                 text='X: calculated input within the existing response range. Y: output within Min/Max. A straight diagonal preserves current behaviour.\n'
                      'White ring: current calculated input. Edits apply live and save automatically; queued output follows after the look-ahead delay.\n'
                      'Volume curves shape the response before primary ceiling / prostate base volume; gain and overrides can change final V0. Other curves shape generated C0/P0/P3/P1.',
                 wraplength=1060).pack(fill='x', padx=20, pady=(4, 14))
        self.refresh()

    def scroll_graphs(self,event):
        widget=event.widget
        if widget.winfo_class()=='TCombobox':return
        while widget not in (self.graph_canvas,self.graph_grid):
            widget=widget.master
            if widget is None:return
        if self.graph_canvas.yview()[1]-self.graph_canvas.yview()[0]>=.999:return
        self.graph_canvas.yview_scroll(-3 if event.delta>0 else 3,'units')
        return 'break'

    def focus_parameter(self,key):
        if key not in self.cards:return
        self.window.update_idletasks()
        for name,card in self.cards.items():
            card.configure(highlightthickness=1,highlightbackground='#7ddfcb' if name==key else CARD)
        self.window.update_idletasks()
        height=max(1,self.graph_grid.winfo_height())
        self.graph_canvas.yview_moveto(max(0,(self.cards[key].winfo_y()-6)/height))

    def refresh_profiles(self):
        self.profile_box['values']=sorted(self.app._parameter_profiles,key=str.casefold)

    def select_profile(self,event=None):
        name=self.profile_choice.get()
        profile=self.app._parameter_profiles.get(name)
        if profile:
            self.profile_name.set(name)
            self.profile_description.set(profile['description'])
            self.profile_status.set('Selected: '+name+' - Load applies it live.')

    def save_profile(self):
        try:
            name=self.app.save_parameter_profile(self.profile_name.get(),self.profile_description.get())
        except (ValueError,OSError) as error:
            messagebox.showerror('Parameter profile',str(error),parent=self.window);return
        self.refresh_profiles();self.profile_choice.set(name);self.profile_name.set(name)
        self.profile_status.set('Saved: '+name)

    def update_description(self):
        name=self.profile_choice.get()
        try:
            self.app.update_parameter_profile_description(name,self.profile_description.get())
        except (ValueError,OSError) as error:
            messagebox.showerror('Parameter profile',str(error),parent=self.window);return
        self.profile_status.set('Description updated: '+name)

    def load_profile(self):
        name=self.profile_choice.get()
        try:
            self.app.apply_parameter_profile(name)
        except (ValueError,OSError) as error:
            messagebox.showerror('Parameter profile',str(error),parent=self.window);return
        self.draft=validate_parameter_curves(self.app._parameter_curves)
        for key,mode in self.modes.items():mode.set(self.draft[key]['interpolation'])
        self.select_profile()
        self.profile_status.set('Loaded: '+name+' - live; Min/Max unchanged')
        self.draw()

    def coords(self, key, x, y):
        c = self.plots[key]
        return 42+x*(max(150, c.winfo_width())-60)/100, 12+(100-y)*(max(100, c.winfo_height())-44)/100

    def data(self, event, key):
        c = self.plots[key]
        return (max(0, min(100, (event.x-42)*100/(max(150,c.winfo_width())-60))),
                max(0, min(100, 100-(event.y-12)*100/(max(100,c.winfo_height())-44))))

    def closest(self, event, key):
        distances = [(math.hypot(event.x-self.coords(key,*p)[0], event.y-self.coords(key,*p)[1]), i)
                     for i,p in enumerate(self.draft[key]['points'])]
        distance, index = min(distances)
        return index if distance <= 12 else None

    def press(self, event, key):
        index = self.closest(event, key)
        self.drag = (key, index) if index is not None else None

    def release(self):
        self.drag = None

    def move(self, event, key):
        if not self.drag or self.drag[0] != key:
            return
        index = self.drag[1]
        points = self.draft[key]['points']
        x,y = self.data(event,key)
        x = points[index][0] if index in (0,len(points)-1) else max(points[index-1][0]+.1,min(points[index+1][0]-.1,x))
        points[index] = [round(x,3),round(y,2)]
        self.changed()

    def add(self, event, key):
        if self.closest(event,key) is not None:
            return
        x,y = self.data(event,key)
        x,y = round(x,3),round(y,2)
        points = self.draft[key]['points']
        if len(points)>=24 or any(abs(x-p[0]) < .1-1e-9 for p in points):
            return
        points.append([x,y]);points.sort(key=lambda p:p[0])
        self.changed()

    def remove(self, event, key):
        index = self.closest(event,key)
        points = self.draft[key]['points']
        if index is not None and index not in (0,len(points)-1):
            del points[index]
            self.changed()

    def change_mode(self,key):
        self.draft[key]['interpolation'] = self.modes[key].get()
        self.changed()

    def change_shape(self,key,variable):
        self.draft[key] = preset(variable.get(),self.modes[key].get())
        variable.set('Shape...')
        self.changed()

    def reset(self):
        from .parameter_curves import default_curves
        self.draft = default_curves()
        for mode in self.modes.values(): mode.set('linear')
        self.changed()

    def discard(self):
        self.draft = validate_parameter_curves(self.opening_curves)
        for key,mode in self.modes.items(): mode.set(self.draft[key]['interpolation'])
        self.changed()

    def changed(self):
        curves = validate_parameter_curves(self.draft)
        self.draft = curves
        self.app.engine.set_parameter_curves(curves)
        self.app._parameter_curves = validate_parameter_curves(curves)
        self.status.set('LIVE - saving changes...')
        if self.save_timer:
            self.window.after_cancel(self.save_timer)
        self.save_timer = self.window.after(350, self.save)
        self.draw()

    def save(self):
        self.save_timer = None
        self.app._save_settings()
        self.status.set('LIVE - changes saved')

    def draw(self):
        snapshot = self.app.engine.parameter_curve_snapshot()
        self.composite.update(self.draft,snapshot)
        applied = self.app._parameter_curves
        signature = (repr(snapshot), repr(self.draft), tuple((c.winfo_width(),c.winfo_height()) for c in self.plots.values()))
        if signature == getattr(self, '_draw_signature', None):
            return
        self._draw_signature = signature
        for key,title,axis,color in PARAMETERS:
            c = painter(self.plots[key]);c.delete('all')
            for tick in (0,25,50,75,100):
                x,y=self.coords(key,tick,tick)
                left,top=self.coords(key,0,100);right,bottom=self.coords(key,100,0)
                c.create_line(x,top,x,bottom,fill='#26374c')
                c.create_line(left,y,right,y,fill='#26374c')
                c.create_text(x,bottom+13,text=str(tick),fill=MUTED,font=('Segoe UI',8))
                c.create_text(left-7,y,text=str(tick),anchor='e',fill=MUTED,font=('Segoe UI',8))
            identity=[*self.coords(key,0,0),*self.coords(key,100,100)]
            c.create_line(*identity,fill='#40536b',dash=(3,4))
            if self.draft[key] != applied[key]:
                line=[v for i in range(101) for v in self.coords(key,i,evaluate(applied[key],i/100)*100)]
                c.create_line(*line,fill='#61778f',width=2,dash=(5,3))
            line=[v for i in range(201) for v in self.coords(key,i/2,evaluate(self.draft[key],i/200)*100)]
            c.create_line(*line,fill=color,width=2)
            for x,y in self.draft[key]['points']:
                px,py=self.coords(key,x,y)
                c.create_oval(px-5,py-5,px+5,py+5,fill=color,outline=PLOT,width=2)
            live=snapshot.get(key)
            if live:
                drive,output,low,high=live
                x,y=self.coords(key,drive*100,evaluate(applied[key],drive)*100)
                c.create_oval(x-4,y-4,x+4,y+4,fill=color,outline='white')
                x,y=self.coords(key,drive*100,evaluate(self.draft[key],drive)*100)
                c.create_oval(x-8,y-8,x+8,y+8,outline='white',width=2)
                curve_output=low+evaluate(self.draft[key],drive)*(high-low)
                self.values[key].set(f'Input {drive:.3f}  |  Curve {curve_output:.3f}  |  Calculated {output:.3f}  |  Range {low:.2f}-{high:.2f}')
            else:
                self.values[key].set('Waiting for a generated sample')
            present(c)

    def refresh(self):
        self.draw()
        self.timer=self.window.after(120,self.refresh)

    def close(self):
        if self.save_timer:
            self.window.after_cancel(self.save_timer)
            self.save()
        if self.timer:self.window.after_cancel(self.timer)
        self.app._parameter_curve_editor=None
        self.window.destroy()
