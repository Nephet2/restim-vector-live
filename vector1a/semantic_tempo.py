"""Semantic tempo controls and a scrollable profiles window."""
import tkinter as tk
from tkinter import ttk


def build_scrollable_semantics(window):
    window.geometry('1000x820')
    window.minsize(900,600)
    window.resizable(True,True)
    shell=ttk.Frame(window);shell.pack(fill='both',expand=True)
    shell.rowconfigure(0,weight=1);shell.columnconfigure(0,weight=1)
    canvas=tk.Canvas(shell,highlightthickness=0,yscrollincrement=24)
    canvas.grid(row=0,column=0,sticky='nsew')
    scroll=ttk.Scrollbar(shell,orient='vertical',command=canvas.yview)
    scroll.grid(row=0,column=1,sticky='ns');canvas.configure(yscrollcommand=scroll.set)
    body=ttk.Frame(canvas,padding=16)
    item=canvas.create_window(0,0,anchor='nw',window=body)
    body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
    def wheel(event):
        if event.widget.winfo_class() in ('TSpinbox','Spinbox','TCombobox','Text','Scale','TScale'):return
        delta=getattr(event,'delta',0)
        if delta:canvas.yview_scroll(-3 if delta>0 else 3,'units');return 'break'
    window.bind('<MouseWheel>',wheel,add='+')
    window.semantic_canvas=canvas
    return body


def add_tempo_controls(app,body,row):
    card=ttk.LabelFrame(body,text='Authored tempo — Gwendolyn / Director',padding=8)
    card.grid(row=row,column=0,columnspan=4,sticky='ew',pady=(0,12))
    for column,(label,scale) in enumerate((('0.5× · slower',.5),('1× · authored',1.),('2× · faster',2.))):
        ttk.Button(card,text=label,command=lambda value=scale:app._apply_semantic_tempo(value)).grid(row=0,column=column,padx=(0,8),sticky='w')
    ttk.Label(card,text='Temporary duration (s)').grid(row=1,column=0,sticky='w',pady=(6,0))
    ttk.Combobox(card,textvariable=app.modifier_tempo_duration_seconds,values=(10,15,30,60,90,120),
                 state='readonly',width=8).grid(row=1,column=1,sticky='w',pady=(6,0))
    ttk.Label(card,textvariable=app.modifier_tempo_status,wraplength=360).grid(row=1,column=2,sticky='w',pady=(6,0))
    ttk.Label(card,text='0.5× / 2× use the synchronized authored timeline, then restore. 1× restores tempo only. Existing 2× duration limits apply.',
              wraplength=760,justify='left',foreground='#555').grid(row=2,column=0,columnspan=3,sticky='w',pady=(6,0))
