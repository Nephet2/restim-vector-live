"""Volume response layout. Reuses existing variables and action callbacks."""
import tkinter as tk
from tkinter import ttk
from .range_bar import RangeBar


def build_volume_response(app, panel):
    def heading(text,row):
        ttk.Label(panel,text=text,font=('TkDefaultFont',10,'bold')).grid(
            row=row,column=0,columnspan=6,sticky='w',pady=(6,4))
    def spin(variable,row,column,low,high,step,apply=True):
        widget=ttk.Spinbox(panel,from_=low,to=high,increment=step,textvariable=variable,width=8,
                           **({'command':app.apply_config} if apply else {}))
        widget.grid(row=row,column=column,sticky='w',padx=(4,10),pady=3)
        return widget
    heading('1 · Generated response',0)
    ttk.Checkbutton(panel,text='Reduce volume at rest',variable=app.dynamic_volume,
                    command=app.apply_config).grid(row=1,column=0,columnspan=2,sticky='w')
    ttk.Label(panel,text='Rest level').grid(row=1,column=2,sticky='e')
    spin(app.volume_rest_level,1,3,0,1,.05)
    ttk.Label(panel,text='Return ramp (s)').grid(row=1,column=4,sticky='e')
    spin(app.volume_ramp_up,1,5,0,10,.1)
    ttk.Label(panel,text='Ramp / speed ratio').grid(row=2,column=0,sticky='w')
    spin(app.volume_ratio,2,1,10,40,1)
    # Input silence before V0, C0, P0, P1 and Prostate V0 drop to rest; longer
    # values ride through script holds, shorter ones react faster to a pause.
    ttk.Label(panel,text='Rest after (s)').grid(row=2,column=2,sticky='e')
    rest_after=spin(app.volume_idle_seconds,2,3,.05,5,.05)
    rest_after.bind('<Return>',lambda event:app.apply_config())
    ttk.Checkbutton(panel,text='Match Primary intensity across spatial modes',variable=app.match_spatial_intensity,
                    command=app._save_settings).grid(row=2,column=4,columnspan=2,sticky='w',padx=8)
    # S-curve fall of V0 / Prostate V0 to rest (0 = instant step), and the stroke
    # reversal needed for input to count as active (0 = off; keeps one-way
    # parking moves such as auto-home at rest).
    ttk.Label(panel,text='Fall time (s)').grid(row=3,column=0,sticky='w')
    fall=spin(app.volume_fall_seconds,3,1,0,5,.1)
    fall.bind('<Return>',lambda event:app.apply_config())
    ttk.Label(panel,text='Reversal window (s)').grid(row=3,column=2,sticky='e')
    window=spin(app.stroke_reversal_window,3,3,0,10,.5)
    window.bind('<Return>',lambda event:app.apply_config())
    ttk.Label(panel,text='0 = off for both',foreground='#555').grid(row=3,column=4,columnspan=2,sticky='w',padx=8)
    app.response_curves_button=ttk.Button(panel,text='Edit response curves',command=app.show_parameter_curves)
    app.response_curves_button.grid(row=4,column=0,sticky='w',pady=5)
    app.volume_response_bar=RangeBar(panel,width=420,minimum_var=app.volume_response_min,
                                    maximum_var=app.volume_response_max,command=app.apply_config)
    app.volume_response_bar.grid(row=4,column=1,columnspan=3,sticky='w',padx=8,pady=5)
    app.volume_response_value=tk.StringVar(value='0.0000')
    value=ttk.Frame(panel);value.grid(row=4,column=4,sticky='w',padx=8)
    ttk.Label(value,text='Primary').pack()
    ttk.Label(value,textvariable=app.volume_response_value,font=('TkDefaultFont',10,'bold')).pack()
    ranges=ttk.Frame(panel);ranges.grid(row=4,column=5,sticky='w')
    for col,(label,variable) in enumerate((('Min',app.volume_response_min),('Max',app.volume_response_max))):
        ttk.Label(ranges,text=label).grid(row=0,column=col*2,padx=(0,4))
        ttk.Spinbox(ranges,from_=0,to=1,increment=.01,width=5,textvariable=variable,
                    command=app.apply_config).grid(row=0,column=col*2+1,padx=(0,6))
    heading('2 · Output levels',5)
    ttk.Label(panel,text='Primary ceiling').grid(row=6,column=0,sticky='w')
    spin(app.four_phase_volume_ceiling,6,1,0,1,.05,apply=False)
    ttk.Label(panel,text='Base volume (Prostate / Neutral)').grid(row=6,column=2,sticky='e')
    spin(app.volume,6,3,0,1,.01)
    ttk.Button(panel,text='Explain volume',command=app.show_volume_guide).grid(row=6,column=4,columnspan=2,sticky='w',padx=8)
    ttk.Label(panel,text=('Primary starts from response × ceiling; matching / Howl can reshape it. Prostate uses its own response × Base volume. '
                          'Zero Base volume mutes both generated outputs. Neutral uses Base volume on both.'),
              wraplength=820,justify='left',foreground='#555').grid(row=7,column=0,columnspan=6,sticky='w',pady=(2,4))
    heading('3 · Composed command',8)
    app.outgoing_volume_value=tk.StringVar(value='Composed V0: no sample yet (before pressure attenuation)')
    ttk.Label(panel,textvariable=app.outgoing_volume_value,font=('TkDefaultFont',10,'bold'),
              wraplength=820,justify='left').grid(row=9,column=0,columnspan=6,sticky='w',pady=3)
    ttk.Label(panel,text='Includes later gains, authored overrides and events. Before pressure attenuation; not confirmation of device receipt.',
              wraplength=820,justify='left',foreground='#555').grid(row=10,column=0,columnspan=6,sticky='w')