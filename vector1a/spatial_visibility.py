"""Presentation-only spatial control visibility; never changes settings."""
from tkinter import ttk

class SpatialVisibility:
    def __init__(self, app, panel, howl_panel, selector):
        self.app, self.panel, self.howl_panel = app, panel, howl_panel
        self.rules = []
        for widget in panel.winfo_children():
            info = widget.grid_info()
            if not info: continue
            row, column = int(info['row']), int(info['column'])
            if row == 10 and column in (0,1):
                widget.grid_configure(row=0, columnspan=5 if column==1 else 1)
            elif row in (4,8,9,12,13,14) or (row==6 and column<4) or (row==7 and column in (0,1,4,5)):
                self.rules.append((widget,'moving'))
            elif (row==10 and column>=2) or (row==11 and column<2):
                self.rules.append((widget,'depth'))
        # Keep six-column controls within the viewport instead of allowing plots
        # and long labels to impose very wide individual columns.
        short_labels = {'Change crossover width with speed':'Speed-linked crossover',
                        'Use different return-stroke crossover':'Return-stroke crossover',
                        'Offset A/B versus C/D timing':'A/B vs C/D timing offset',
                        'Bias sequence within each stroke':'Stroke sequence bias',
                        'Add slow volume variation':'Slow volume variation'}
        for widget in panel.winfo_children():
            info=widget.grid_info()
            if not info:continue
            row,col=int(info['row']),int(info['column'])
            if widget.winfo_class()=='TCheckbutton':
                text=widget.cget('text')
                if text in short_labels:widget.configure(text=short_labels[text])
            if widget.winfo_class()=='TLabel':
                widget.configure(wraplength=150 if int(info.get('columnspan',1))==1 else 780)
            if row in (20,21,22,23):
                if col==2:
                    widget.configure(length=260)
                    widget.grid_configure(columnspan=3,sticky='ew')
                elif col==3:
                    widget.grid_remove()
                elif col==4:
                    widget.grid_configure(column=5)
                elif col==5:
                    widget.configure(width=1,wraplength=780)
                    widget.grid_configure(row=25,column=0,columnspan=6,rowspan=1,sticky='ew')
        panel.columnconfigure(2,weight=1)
        self.custom_button = next(w for w in selector.winfo_children() if w.winfo_class()=='TButton')
        self.custom_pack = self.custom_button.pack_info()
        self.howl_rules=[]
        for widget in howl_panel.winfo_children():
            info=widget.grid_info();row,col=int(info['row']),int(info['column'])
            kind=None
            if row in (0,1) and col==0:kind='positional'
            elif row in (0,1) and col==1:kind='dynamic'
            elif (row in (0,1) and col==4) or row==3 or (row in (4,5) and col in (0,1)):kind='pulse'
            elif row==2:kind='howl'
            if kind:self.howl_rules.append((widget,kind))
        self.note=ttk.Label(panel,wraplength=800,justify='left',foreground='#555')
        self.note.grid(row=1,column=0,columnspan=6,sticky='ew',pady=(4,8))
        for variable in (app.four_phase_spatial_model,app.match_spatial_intensity,app.howl_pulse):
            variable.trace_add('write',self.refresh)
        self.refresh()

    @staticmethod
    def show(widget, visible):
        if visible:widget.grid()
        else:widget.grid_remove()

    def refresh(self,*_args):
        model=self.app.four_phase_spatial_model.get()
        moving=model=='Moving focus';depth=model=='Depth spread';howl=model.startswith('Howl ')
        matching=self.app.match_spatial_intensity.get()
        for widget,kind in self.rules:self.show(widget,moving if kind=='moving' else depth)
        if model=='Custom':self.custom_button.pack(**self.custom_pack)
        else:self.custom_button.pack_forget()
        self.show(self.howl_panel,howl or matching)
        self.howl_panel.configure(text='Howl conversion' if howl else 'Intensity matching — Howl amplitude controls')
        for widget,kind in self.howl_rules:
            visible={'positional':model=='Howl Positional','dynamic':model=='Howl Dynamic',
                     'howl':howl,'pulse':howl and self.app.howl_pulse.get()}[kind]
            self.show(widget,visible)
        if moving:
            message='Moving focus: crossover, return stroke, width texture, group delay and sequence effects are available. Depth shaping and Custom curves are bypassed.'
        elif depth:
            message='Depth spread: depth shaping and static electrode order apply. Crossover, sequence effects and group delay are bypassed.'
        elif model=='Custom':
            message='Custom: edit the spatial curves; static electrode order and focus still apply. Crossover, depth shaping, sequence effects and group delay are bypassed.'
        else:
            message=model+': raw-L0 conversion and static electrode order apply. Crossover, depth shaping, sequence effects and group delay are bypassed.'
        if matching and not howl:message+=' Intensity matching is on, so its Howl amplitude controls remain available.'
        self.note.configure(text=message+'\nSpatial position controls shape four-phase E1-E4, not the three-phase alpha/beta plot. Common volume settings and Howl pulse options still affect outgoing commands. Hidden settings are retained.')
