"""Read-only diagnostics presentation using existing health snapshots."""
import tkinter as tk
from tkinter import ttk

from .signal_quality_panel import SignalQualityPanel


def age(value):
    return 'never' if value is None else f'{max(0.,float(value)):.2f} s ago'


def transport_text(health, lane):
    return (f"Socket: {'connected' if health['connected'] else 'disconnected'}\n"
            f"Successful socket writes: {health['send_count']}\n"
            f"Last socket write: {age(health['tx_age'])}\n"
            f"Sender: {'running' if lane['alive'] else 'not running'}; pending: {'yes' if lane['pending'] else 'no'}\n"
            f"Superseded frames: {lane['dropped']}; expired: {lane['stale']}\n"
            f"Failures: socket {health['send_failures']}; sender {lane['failures']}")

class DiagnosticsPanel:
    def __init__(self, app, panel):
        self.app=app
        self.notebook=ttk.Notebook(panel);self.notebook.pack(fill='both',expand=True)
        self.overview=ttk.Frame(self.notebook,padding=8)
        self.samples=ttk.Frame(self.notebook,padding=8)
        self.notebook.add(self.overview,text='Signal path')
        self.notebook.add(self.samples,text='Calculated samples')
        quality = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(quality, text='Signal Quality')
        self.signal_quality = SignalQualityPanel(quality, app.restim, app.prostate_restim,
                                                 popout=self.open_popout)
        # Optional separate Signal Quality window, kept visible while adjusting
        # settings elsewhere in the main window.
        self.popout_window = None
        self.popout_panel = None
        self.popout_on_top = tk.BooleanVar(value=False)
        for col in (0,1):self.overview.columnconfigure(col,weight=1,uniform='stages')
        self.stage_vars={name:tk.StringVar(value='Waiting for refresh') for name in ('source','primary','prostate','primary_address','prostate_address')}
        def card(title,row,col):
            frame=ttk.LabelFrame(self.overview,text=title,padding=8)
            frame.grid(row=row,column=col,sticky='nsew',padx=4,pady=4)
            frame.columnconfigure(0,weight=1)
            return frame
        def text(frame,variable,row):
            ttk.Label(frame,textvariable=variable,wraplength=390,justify='left',width=1).grid(row=row,column=0,sticky='ew',pady=2)
        source=card('1 · Incoming data',0,0)
        text(source,app.mfp_status,0);text(source,self.stage_vars['source'],1)
        ttk.Label(source,text='An input gap does not stop Vector output. Use STOP to stop output.',
                  wraplength=390,justify='left',foreground='#555').grid(row=2,column=0,sticky='w',pady=(5,0))
        engine=card('2 · Engine calculation',0,1)
        for row,(label,key) in enumerate((('State','state'),('Engine input samples','input_count'),
                                          ('Released samples','output_count'),('Buffer','buffer'),
                                          ('Look-ahead','lookahead'),('Queue delay','actual_delay'))):
            line=ttk.Frame(engine);line.grid(row=row,column=0,sticky='ew')
            ttk.Label(line,text=label+': ',width=22).pack(side='left')
            ttk.Label(line,textvariable=app.diag_vars[key]).pack(side='left')
        composed=card('3 · Composed command',1,0)
        text(composed,app.outgoing_volume_value,0)
        ttk.Label(composed,text='After gains, authored overrides and events; before pressure attenuation. These are calculated values, not device acknowledgements.',
                  wraplength=390,justify='left',foreground='#555').grid(row=1,column=0,sticky='w',pady=5)
        transport=card('4 · Connection / socket writes',1,1)
        ttk.Label(transport,text='PRIMARY',font=('TkDefaultFont',9,'bold')).grid(row=0,column=0,sticky='w')
        text(transport,self.stage_vars['primary_address'],1);text(transport,self.stage_vars['primary'],2)
        ttk.Separator(transport).grid(row=3,column=0,sticky='ew',pady=5)
        ttk.Label(transport,text='PROSTATE',font=('TkDefaultFont',9,'bold')).grid(row=4,column=0,sticky='w')
        text(transport,self.stage_vars['prostate_address'],5);text(transport,self.stage_vars['prostate'],6)
        ttk.Label(self.overview,text='Socket writes do not confirm ReStim processing or physical output. Addresses shown are configured fields; changing them does not reconnect.',
                  wraplength=820,justify='left',foreground='#555').grid(row=2,column=0,columnspan=2,sticky='w',padx=5,pady=5)
        fields=(('Engine input L0','raw_l0'),('Generated L0','output_l0'),('Calculated speed','speed'),
                ('Generated Primary alpha','alpha'),('Generated Primary beta','beta'),
                ('Engine state','state'),('Active calculation','active_mode'),('Released sample mode','output_mode'),
                ('Generated Primary volume','output_volume'),('Frequency (0–1)','frequency'),
                ('Pulse frequency (0–1)','pulse_frequency'),('Pulse rise time (0–1)','pulse_rise_time'),
                ('Pulse width (0–1)','pulse_width'),('Generated Prostate alpha','alpha_prostate'),
                ('Generated Prostate beta','beta_prostate'),('Generated Prostate volume','volume_prostate'))
        for i,(label,key) in enumerate(fields):
            row,col=i//2,(i%2)*2
            ttk.Label(self.samples,text=label,wraplength=170).grid(row=row,column=col,sticky='w',padx=6,pady=5)
            ttk.Label(self.samples,textvariable=app.diag_vars[key],wraplength=220).grid(row=row,column=col+1,sticky='w',padx=6,pady=5)
        ttk.Label(self.samples,text='Generated samples precede final composition. Authored axes, Howl pulse overrides, focus and events can change outgoing values.',
                  wraplength=820,justify='left',foreground='#555').grid(row=9,column=0,columnspan=4,sticky='w',pady=8)

    def open_popout(self):
        """Show Signal Quality in its own window; a second press raises it."""
        window = self.popout_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return
        window = tk.Toplevel(self.app.root)
        window.title('Signal Quality — Vector')
        window.geometry('760x560')
        window.minsize(520, 420)
        window.resizable(True, True)
        window.protocol('WM_DELETE_WINDOW', self.close_popout)
        body = ttk.Frame(window, padding=8)
        body.pack(fill='both', expand=True)
        ttk.Checkbutton(body, text='Keep on top', variable=self.popout_on_top,
                        command=self.apply_popout_on_top).pack(anchor='e')
        self.popout_window = window
        self.popout_panel = SignalQualityPanel(body, self.app.restim, self.app.prostate_restim)
        self.popout_panel.copy_selections_from(self.signal_quality)
        self.apply_popout_on_top()
        window.update_idletasks()
        self.popout_panel.refresh(force=True)

    def apply_popout_on_top(self):
        window = self.popout_window
        if window is not None and window.winfo_exists():
            window.attributes('-topmost', bool(self.popout_on_top.get()))

    def close_popout(self):
        window = self.popout_window
        self.popout_window = self.popout_panel = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def refresh(self):
        self.signal_quality.refresh()
        if self.popout_panel is not None:
            if self.popout_window is not None and self.popout_window.winfo_exists():
                self.popout_panel.refresh()
            else:
                self.popout_window = self.popout_panel = None
        app=self.app;source=app.listener.health()
        fresh=source['last_l0_age']
        incoming='No MFP L0 received' if fresh is None else f"Last MFP L0: {age(fresh)}; authored position: {app.input_pipeline.latest_authored_l0:.4f}"
        self.stage_vars['source'].set(incoming+f"\nGenerated-motion source: {'active' if app.generated_motion.active else 'inactive'}")
        for name,client,sender,host,port in (
                ('primary',app.restim,app.restim_sender,app.restim_host,app.restim_port),
                ('prostate',app.prostate_restim,app.prostate_sender,app.prostate_host,app.prostate_port)):
            try:address=f'Configured: {host.get()}:{port.get()}'
            except tk.TclError:address='Configured: incomplete entry'
            self.stage_vars[name+'_address'].set(address)
            self.stage_vars[name].set(transport_text(client.health(),sender.health()))
