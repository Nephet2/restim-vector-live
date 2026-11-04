"""Main-window navigation and grouped actions; no signal or persistence changes."""
import tkinter as tk
from tkinter import ttk


def jump_to_section(app, title):
    section = app.sections[title]
    if section.collapsed:
        section.collapsed = False
        section._render()
    app.root.update_idletasks()
    bounds = app.main_canvas.bbox('all')
    if bounds:
        app.main_canvas.yview_moveto(max(0., (section.winfo_y()-6) / max(1, bounds[3]-bounds[1])))
    section.button.focus_set()


def build_navigation(app):
    header = ttk.Frame(app.root, padding=(12, 6))
    header.grid(row=0, column=0, sticky='ew')
    header.columnconfigure(0, weight=1)
    controls = ttk.Frame(header)
    controls.grid(row=0, column=0, sticky='ew')
    ttk.Label(controls, text='Vector Live', font=('TkDefaultFont', 11, 'bold')).pack(side='left', padx=(0,16))
    for label, action in (('START / RESUME',app.resume),('Neutral',app.neutral),('STOP',app.stop),
                          ('Pressure',lambda:app.pressure_control.show(app.root,app.stop))):
        ttk.Button(controls,text=label,command=action).pack(side='left',padx=(0,6))
    ttk.Label(controls,textvariable=app.diag_vars['state'],width=12,anchor='e').pack(side='right')

    navigation = ttk.Frame(header)
    navigation.grid(row=1,column=0,sticky='ew',pady=(6,0))
    groups = (
        ('Session',(('Session startup',app.show_session_startup),('Director',app.show_director_window))),
        ('Presets & tools',(('Presets A/B',app.show_preset_window),('Semantic profiles',app.show_director_semantic_window),
                           ('Response curves',app.show_parameter_curves),('Spatial curves',app.show_custom_curves),
                           ('Rolling Variety',app.show_variety_window),('Script modifiers',app.show_modifier_window))),
        ('Connections',(('MFP input panel',lambda:jump_to_section(app,'MultiFunPlayer input')),
                        ('ReStim output panel',lambda:jump_to_section(app,'ReStim output')),
                        ('MFP axes',app.show_axis_routing),('Connection log',app.show_connection_log))),
        ('Help',(('Setup guide',app.show_setup_guide),('Volume response',app.show_volume_guide),
                  ('Motion controls',app.show_motion_guide),('Primary spatial controls',app.show_four_phase_guide))),
    )
    app.navigation_menus = {}
    for label, actions in groups:
        button = ttk.Menubutton(navigation,text=label)
        menu = tk.Menu(button,tearoff=False)
        for title,action in actions:menu.add_command(label=title,command=action)
        button.configure(menu=menu);button.pack(side='left',padx=(0,6))
        app.navigation_menus[label] = menu
    ttk.Separator(navigation,orient='vertical').pack(side='left',fill='y',padx=6)
    app.section_shortcuts = {}
    for label,section in (('Motion','Motion'),('Response','Volume response'),
                           ('Primary','Four-phase primary motion'),('Prostate','Prostate controls'),
                           ('Diagnostics','Live diagnostics')):
        button = ttk.Button(navigation,text=label,width=10,
                            command=lambda title=section:jump_to_section(app,title))
        button.pack(side='left',padx=(0,4))
        app.section_shortcuts[section] = button
    status = ttk.Frame(header)
    status.grid(row=2,column=0,sticky='ew',pady=(5,0))
    status.columnconfigure(0,weight=1);status.columnconfigure(1,weight=1)
    ttk.Label(status,textvariable=app.session_ready_status,width=1,anchor='w').grid(row=0,column=0,sticky='ew')
    ttk.Label(status,textvariable=app.director_status,width=1,anchor='e').grid(row=0,column=1,sticky='ew')
    app.navigation_header = header
