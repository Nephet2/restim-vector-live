"""Settings document migration and profile mapping, without UI or filesystem I/O."""
from copy import deepcopy
from dataclasses import dataclass
from .parameter_curves import default_curves, validate_parameter_curves, validated_parameter_profiles
from .custom_spatial import make_preset, validate_curves, validated_profiles

STATE_KEYS = {
    'parameter_response_profiles': '_parameter_profiles',
    'parameter_response_curves': '_parameter_curves',
    'custom_spatial_curves': '_custom_curves',
    'custom_spatial_profiles': '_custom_profiles',
    'active_custom_profile': '_active_custom_profile_name',
    'four_phase_presets': '_preset_slots',
    'director_texture_profiles': '_director_texture_profiles',
    'director_variation_profiles': '_director_variation_profiles',
    'director_top_focus_profiles': '_director_top_focus_profiles',
    'director_bottom_focus_profiles': '_director_bottom_focus_profiles',
}

@dataclass
class DecodedSettings:
    scalars: dict
    state: dict
    presets: dict
    routes: list | None
    routing_mode: str | None
    selections: dict
    first_run: bool

class SettingsCodec:
    def __init__(self, fields, profile_names, selection_names):
        self.fields = tuple(dict.fromkeys(fields))
        self.profile_names = profile_names
        self.selection_names = selection_names

    def decode(self, document):
        saved = deepcopy(document)
        if 'modifier_stroke_range' not in saved and 'modifier_range_scale' in saved:
            saved['modifier_stroke_range'] = saved.get('modifier_range_scale', 1.0)
        scalars = {name: saved[name] for name in self.fields if name in saved}
        try:
            curves = validate_parameter_curves(saved.get('parameter_response_curves', default_curves()))
        except (ValueError, TypeError):
            curves = default_curves()
        state = {'_parameter_curves': curves,
                 '_parameter_profiles': validated_parameter_profiles(saved.get('parameter_response_profiles', {})),
                 '_custom_profiles': validated_profiles(saved.get('custom_spatial_profiles', {}))}
        if 'custom_spatial_curves' in saved:
            try:
                state['_custom_curves'] = validate_curves(saved['custom_spatial_curves'])
            except (ValueError, TypeError):
                state['_custom_curves'] = make_preset('Moving focus')
        active = saved.get('active_custom_profile')
        state['_active_custom_profile_name'] = active if isinstance(active, str) and active in state['_custom_profiles'] else None
        for kind, names in self.profile_names.items():
            profiles = saved.get('director_'+kind+'_profiles', {})
            if isinstance(profiles, dict):
                state['_director_'+kind+'_profiles'] = {
                    name: profile for name, profile in profiles.items()
                    if name in names and isinstance(profile, dict)}
        slots = saved.get('four_phase_presets', {})
        presets = {slot: slots[slot] for slot in ('A','B') if isinstance(slots.get(slot),dict)} if isinstance(slots,dict) else {}
        routes = saved.get('authored_axis_routes', [])
        mode = saved.get('authored_routing_mode')
        return DecodedSettings(scalars, state, presets,
            routes if isinstance(routes,list) else None,
            mode if mode in ('Manual selected axes','Auto authored ReStim set') else None,
            {name:saved[name] for name,names in self.selection_names.items() if saved.get(name) in names},
            not bool(saved.get('first_run_complete')))

    def encode(self, scalars, state, routes, routing_mode, selections):
        values = {name:scalars[name] for name in self.fields}
        values.update({key:state[attr] for key,attr in STATE_KEYS.items()})
        values['parameter_response_profiles'] = validated_parameter_profiles(state['_parameter_profiles'])
        values['parameter_response_curves'] = validate_parameter_curves(state['_parameter_curves'])
        values['authored_axis_routes'] = sorted(routes)
        values['authored_routing_mode'] = routing_mode
        values.update(selections)
        values['first_run_complete'] = True
        return deepcopy(values)
