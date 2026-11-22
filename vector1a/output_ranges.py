import math


def unit_range(low, high):
    """Finite, ordered normalized bounds, including a fixed-value range."""
    low, high = float(low), float(high)
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError("Range bounds must be finite")
    return tuple(sorted((min(1., max(0., low)), min(1., max(0., high)))))


def scale_response(value, low, high):
    low, high = unit_range(low, high)
    return low + min(1., max(0., float(value))) * (high - low)



def match_volume_response(response, intensity, rest_response):
    """Keep spatial intensity inside the running response and idle floor.

    The current response is also the return-ramp ceiling. Stop/Neutral bypass
    this running calculation. Later explicit gains and authored overrides retain
    ownership of their final output.
    """
    response = min(1., max(0., float(response)))
    floor = min(response, max(0., float(rest_response)))
    return min(response, max(floor, float(intensity)))
