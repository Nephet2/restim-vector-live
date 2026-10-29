"""Independent bounded response curves for generated parameter axes."""
from .spatial_curves_math import evaluate, validate_curve, preset

PARAMETERS = (
    ('primary_volume', 'Primary volume', 'V0 main', '#ef97b9'),
    ('prostate_volume', 'Prostate volume', 'V0 P', '#7bbcff'),
    ('frequency', 'Frequency', 'C0', '#7ddfcb'),
    ('pulse_frequency', 'Pulse frequency', 'P0', '#f1b095'),
    ('pulse_rise_time', 'Pulse rise time', 'P3', '#adadff'),
    ('pulse_width', 'Pulse width', 'P1', '#ecd17e'),
)


def default_curves():
    return {key: preset('rising', 'linear') for key, *_ in PARAMETERS}


def validate_parameter_curves(curves):
    expected = {p[0] for p in PARAMETERS}
    legacy = expected - {'primary_volume', 'prostate_volume'}
    if not isinstance(curves, dict) or set(curves) not in (expected, legacy):
        raise ValueError('One curve is required for each parameter')
    # Preview 1/2 settings and named profiles retain their four shapes exactly.
    merged = default_curves()
    merged.update(curves)
    return {key: validate_curve(merged[key]) for key, *_ in PARAMETERS}


def validate_parameter_profile(name, description, curves):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('Profile name must be 1-80 characters')
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError('Description must be at most 500 characters')
    return name.strip(), {'description': description.strip(),
                          'curves': validate_parameter_curves(curves)}


def validated_parameter_profiles(data):
    if not isinstance(data, dict):
        return {}
    result = {}
    for name, profile in data.items():
        if len(result) >= 100:
            break
        try:
            name, profile = validate_parameter_profile(name, profile.get('description', ''), profile.get('curves'))
            result[name] = profile
        except (ValueError, TypeError, AttributeError):
            continue
    return result


def shape_output(curve, value, low, high):
    """Shape normalized range position; identity preserves baseline arithmetic."""
    drive = min(1., max(0., (value-low)/(high-low))) if high > low else 0.
    if curve == {'points': [[0, 0], [100, 100]], 'interpolation': 'linear'}:
        return value, drive
    return low + evaluate(curve, drive)*(high-low), drive
