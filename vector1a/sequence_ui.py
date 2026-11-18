"""Ceiling-relative preset sequencer, independent of the AI Director."""
import tkinter as tk
import math
from tkinter import ttk, messagebox
from .passage_sequence import SequencePlan
from .motion import MotionMode, numbered_mode_box


def controller_display(p):
    """Render controller readback, never the editable preview or AI narration."""
    detail=p.get('sequence') or {}
    phase=p.get('phase','idle')
    if p.get('completed') or phase=='complete':
        cue,color='COMPLETED','#90a4b8'
    elif phase=='restoring':
        cue,color='RETURNING TO BASELINE','#efc46b'
    elif not p.get('active'):
        cue,color='NO ACTIVE SEQUENCE','#90a4b8'
    else:
        cue,color={'red_light':('RED LIGHT','#ff6868'),
                   'green_light':('GREEN LIGHT','#5be0a2')}.get(
                       detail.get('game_phase'),('SEQUENCE ACTIVE' if detail else 'PASSAGE ACTIVE','#80c9ff'))
        if p.get('held'):cue+=' — HELD'
        elif p.get('reason'):cue+=' — PAUSED / WAITING'
    seconds=max(0,math.ceil(p.get('remaining_seconds',0)))
    remaining=f'{seconds//60:02d}:{seconds%60:02d} remaining'
    step=f"Step {detail['step_index']+1} | " if detail and p.get('active') else ''
    ceiling=p.get('nominal_ceiling')
    level=f' | controller ceiling {ceiling:.0%}' if ceiling is not None else ''
    status=f"{step}{phase} | {remaining}{level}"
    if p.get('reason'):status+=f" | {p['reason']}"
    return cue,color,status


def show_sequences(app):
    existing=getattr(app,'_sequence_window',None)
    if existing is not None and existing.winfo_exists(): existing.lift();return
    w=tk.Toplevel(app.root);app._sequence_window=w
    w.title('Vector - ceiling-relative passage sequencer');w.geometry('860x810');w.minsize(800,810)
    b=ttk.Frame(w,padding=14);b.pack(fill='both',expand=True);b.columnconfigure(1,weight=1)
    ttk.Label(b,text='Narrative passage sequence',font=('TkDefaultFont',13,'bold')).grid(row=0,column=0,columnspan=4,sticky='w')
    ttk.Label(b,text='Each preset starts and returns at the Primary ceiling captured when you Apply.\n'
              'Build & release rises toward Peak; Tease & return dips toward Low. Secondary output is unchanged.',
              wraplength=800).grid(row=1,column=0,columnspan=4,sticky='w',pady=8)
    fields={}
    for col,(key,label,value) in enumerate((('out_seconds','Out (s)','30'),('hold_seconds','Hold (s)','10'),('return_seconds','Return (s)','30'),('peak','Peak %','100'),('low','Low %',f'{app.four_phase_volume_ceiling.get()*65:.1f}'))):
        fields[key]=tk.StringVar(value=value)
        ttk.Label(b,text=label).grid(row=2,column=col,sticky='w')
        ttk.Entry(b,textvariable=fields[key],width=11).grid(row=3,column=col,sticky='w')
    steps=[];listing=tk.Listbox(b,height=6)
    listing.grid(row=5,column=0,columnspan=5,sticky='ew',pady=8)
    def refresh_list():
        listing.delete(0,'end')
        for i,s in enumerate(steps):
            listing.insert('end',f"{i+1}. {s['preset'].replace('_',' ')} - {s['out_seconds']:g}/{s['hold_seconds']:g}/{s['return_seconds']:g}s - destination {s['level']:.0%}")
    def add(preset):
        try:
            step={k:float(fields[k].get()) for k in ('out_seconds','hold_seconds','return_seconds')}
            step.update(preset=preset,level=float(fields['peak' if preset=='build_release' else 'low'].get())/100)
            SequencePlan.validated({'steps':[step]},app.four_phase_volume_ceiling.get())
            if len(steps)>=16:raise ValueError('At most 16 steps')
            steps.append(step);refresh_list();draw()
        except ValueError as e:messagebox.showerror('Sequence',str(e),parent=w)
    buttons=ttk.Frame(b);buttons.grid(row=4,column=0,columnspan=5,sticky='w',pady=8)
    for label,preset in (('Add build & release','build_release'),('Add tease & return','tease_return')):
        ttk.Button(buttons,text=label,command=lambda p=preset:add(p)).pack(side='left',padx=(0,6))
    def remove():
        if listing.curselection():steps.pop(listing.curselection()[0]);refresh_list();draw()
    def move(delta):
        if listing.curselection():
            i=listing.curselection()[0];j=i+delta
            if 0<=j<len(steps):steps[i],steps[j]=steps[j],steps[i];refresh_list();listing.selection_set(j);draw()
    ttk.Button(buttons,text='Remove',command=remove).pack(side='left',padx=3)
    ttk.Button(buttons,text='Up',command=lambda:move(-1)).pack(side='left',padx=3)
    ttk.Button(buttons,text='Down',command=lambda:move(1)).pack(side='left',padx=3)
    clock=tk.StringVar(value='elapsed');label=tk.StringVar(value='Red light / green light')
    ttk.Label(b,text='Clock').grid(row=6,column=0,sticky='w')
    ttk.Combobox(b,textvariable=clock,values=('elapsed','media'),state='readonly',width=12).grid(row=6,column=1,sticky='w')
    ttk.Label(b,text='Narrative intention').grid(row=7,column=0,sticky='w',pady=6)
    ttk.Entry(b,textvariable=label).grid(row=7,column=1,columnspan=4,sticky='ew')
    canvas=tk.Canvas(b,height=130,bg='#13202e',highlightthickness=0)
    canvas.grid(row=8,column=0,columnspan=5,sticky='ew',pady=8)
    def plan():return SequencePlan.validated({'steps':list(steps),'clock':clock.get(),'label':label.get()},app.four_phase_volume_ceiling.get())
    def draw(event=None):
        canvas.delete('all')
        if not steps:return
        try:
            p=plan();width=max(500,canvas.winfo_width());pts=[]
            baseline_y=110-90*p.baseline
            canvas.create_line(15,baseline_y,width-15,baseline_y,fill='#8193a5',dash=(4,4))
            for v in p.preview():pts.extend((15+(width-30)*v['seconds']/p.duration,110-90*v['ceiling']))
            canvas.create_line(*pts,fill='#5bd9bd',width=3)
            canvas.create_text(18,120,anchor='w',fill='white',text=f'Baseline {p.baseline:.0%} | total {p.duration:g}s | ceiling targets; live response remains dynamic')
        except ValueError as e:canvas.create_text(15,30,anchor='w',text=str(e),fill='white')
    canvas.bind('<Configure>',draw)
    def apply():
        try:
            state=app.engine.control_state()
            if state['engine_state']!='Running' or not state['output_enabled']:raise ValueError('Start Vector manually first')
            app.passage.apply(plan())
        except ValueError as e:messagebox.showerror('Sequence',str(e),parent=w)
    actions=ttk.Frame(b);actions.grid(row=9,column=0,columnspan=5,sticky='w')
    for text,fn in (('Preview',draw),('Apply sequence',apply),('Hold',app.passage.hold),('Resume',app.passage.resume),('Return to baseline',app.passage.restore)):
        ttk.Button(actions,text=text,command=fn).pack(side='left',padx=(0,5))
    live=ttk.LabelFrame(b,text='Live controller readback (not the preview)',padding=8)
    live.grid(row=10,column=0,columnspan=5,sticky='ew',pady=8)
    cue=tk.Label(live,text='',font=('TkDefaultFont',17,'bold'),bg='#13202e',anchor='w',padx=8,pady=4)
    cue.pack(fill='x')
    status=tk.StringVar();ttk.Label(live,textvariable=status,wraplength=760).pack(anchor='w',pady=(4,0))
    motion=ttk.LabelFrame(b,text='Primary three-phase motion geometry (alpha / beta)',padding=8)
    motion.grid(row=11,column=0,columnspan=5,sticky='ew')
    mode=tk.StringVar(value=app.mode.get())
    numbered_mode_box(motion,mode,width=48).pack(side='left')
    def change_mode():
        app.engine.set_motion_mode(MotionMode(mode.get()));app.mode.set(mode.get());app.apply_config()
    ttk.Button(motion,text='Apply mode',command=change_mode).pack(side='left',padx=8)
    ttk.Label(b,text='Mode changes preserve volume controls; queued samples finish, then alpha/beta blend for 2 seconds.\n'
              'Four-phase E1-E4 use their separate spatial model. Perceived strength can still change.',wraplength=800).grid(row=12,column=0,columnspan=5,sticky='w',pady=5)
    def advanced():
        from .passage_ui import show_passages
        show_passages(app)
    ttk.Button(b,text='Generated motion / legacy attenuation workbench...',command=advanced).grid(row=13,column=0,columnspan=5,sticky='w',pady=5)
    ttk.Button(b,text='Load / sync authored funscript timeline...',command=app.show_timeline_window).grid(row=14,column=0,columnspan=5,sticky='w',pady=5)
    def tick():
        if not w.winfo_exists():return
        text,color,description=controller_display(app.passage.snapshot())
        cue.configure(text=text,fg=color)
        status.set(description)
        w.after(250,tick)
    # An editable example; no output is changed until Apply.
    if app.four_phase_volume_ceiling.get() > 0:
        for preset in ('tease_return','build_release','build_release','tease_return'):add(preset)
    tick()
