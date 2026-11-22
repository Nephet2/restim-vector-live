from __future__ import annotations

import math

ELECTRODE_ORDERS = ("ABCD", "ABDC", "BACD", "ACBD")
SPATIAL_MODELS = ("Moving focus", "Depth spread", "Howl Positional", "Howl Dynamic", "Custom")


def adaptive_crossover_width(speed_percent: float, slow_width: float,
                             fast_width: float) -> float:
    """Interpolate crossover width from slow to fast using normalized speed."""
    speed = min(1.0, max(0.0, speed_percent / 100.0))
    slow = min(1.0, max(.05, slow_width))
    fast = min(1.0, max(.05, fast_width))
    # Smoothstep avoids a sharp response at either end of the speed range.
    blend = speed * speed * (3.0 - 2.0 * speed)
    return slow + (fast - slow) * blend


def directional_crossover_profile(direction: int, width: float, curve: str,
                                  sharpness: float, enabled: bool,
                                  reverse_width_scale: float,
                                  reverse_curve: str,
                                  reverse_sharpness: float
                                  ) -> tuple[float, str, float, str]:
    """Select a continuous forward/reverse crossover profile."""
    width = min(1.0, max(.05, width))
    sharpness = min(5.0, max(.2, sharpness))
    if enabled and direction < 0:
        scale = min(3.0, max(.2, reverse_width_scale))
        return (min(1.0, max(.05, width * scale)), reverse_curve,
                min(5.0, max(.2, reverse_sharpness)), "reverse")
    return width, curve, sharpness, "forward"


def spatial_response(position: float, curve: str = "Linear",
                     blend: float = 1.0) -> float:
    """Monotonically reshape a four-phase path while preserving 0, .5 and 1."""
    position = min(1.0, max(0.0, position))
    blend = min(1.0, max(0.0, blend))
    name = curve.strip().lower()
    if name in ("s-curve", "s curve"):
        shaped = position * position * (3.0 - 2.0 * position)
    elif name in ("endpoint emphasis", "endpoints"):
        distance = abs(position - .5) * 2.0
        shaped = .5 + math.copysign(.5 * math.sqrt(distance), position - .5)
    elif name in ("centre emphasis", "center emphasis", "centre", "center"):
        distance = abs(position - .5) * 2.0
        shaped = .5 + math.copysign(.5 * distance * distance, position - .5)
    else:
        shaped = position
    return position + (shaped - position) * blend


def reversal_emphasis_envelope(distance_seconds: float,
                               window_seconds: float) -> float:
    """Cosine emphasis centred on a known stroke reversal."""
    window = max(.01, window_seconds)
    distance = abs(distance_seconds)
    if not math.isfinite(distance) or distance >= window:
        return 0.0
    return (1.0 + math.cos(math.pi * distance / window)) / 2.0


def proportional_reversal_boost(volume: float, envelope: float,
                                boost_fraction: float) -> float:
    """Boost current volume proportionally, with an absolute 0..1 clamp."""
    volume = min(1.0, max(0.0, float(volume)))
    envelope = min(1.0, max(0.0, float(envelope)))
    boost = min(1.0, max(0.0, float(boost_fraction)))
    return min(1.0, volume * (1.0 + envelope * boost))


def stroke_phase_crossover(width: float, progress: float, enabled: bool,
                           acceleration_scale: float,
                           deceleration_scale: float) -> tuple[float, str]:
    """Smoothly vary crossover width from stroke start to stroke end."""
    width = min(1.0, max(.05, width))
    progress = min(1.0, max(0.0, progress))
    if not enabled:
        return width, "off"
    acceleration_scale = min(3.0, max(.2, acceleration_scale))
    deceleration_scale = min(3.0, max(.2, deceleration_scale))
    blend = progress * progress * (3.0 - 2.0 * progress)
    scale = acceleration_scale + (deceleration_scale - acceleration_scale) * blend
    phase = "accelerating" if progress < .5 else "decelerating"
    return min(1.0, max(.05, width * scale)), phase


def pair_swapped_order(order: str) -> str:
    """Return the discrete destination of a full A/B + C/D pair morph."""
    if order not in ELECTRODE_ORDERS:
        order = "ABCD"
    return order.translate(str.maketrans("ABCD", "BADC"))


def sequence_cycle_stage(base_order: str, cycle_position: float,
                         transition_fraction: float = 1.0
                         ) -> tuple[str, str, float]:
    """Return source, destination and eased progress for the order carousel.

    Each stage holds its source sequence before using the final
    ``transition_fraction`` of the stage to morph to the destination.
    """
    if base_order not in ELECTRODE_ORDERS:
        base_order = ELECTRODE_ORDERS[0]
    cycle_position = cycle_position % 1.0
    scaled = cycle_position * len(ELECTRODE_ORDERS)
    stage = min(len(ELECTRODE_ORDERS) - 1, int(scaled))
    local = scaled - stage
    start_index = (ELECTRODE_ORDERS.index(base_order) + stage) % len(ELECTRODE_ORDERS)
    source = ELECTRODE_ORDERS[start_index]
    destination = ELECTRODE_ORDERS[(start_index + 1) % len(ELECTRODE_ORDERS)]
    transition_fraction = min(1.0, max(1e-6, transition_fraction))
    transition_start = 1.0 - transition_fraction
    transition_progress = min(1.0, max(0.0,
        (local - transition_start) / transition_fraction))
    eased = (1.0 - math.cos(transition_progress * math.pi)) / 2.0
    return source, destination, eased


def moving_sequence_window(base_order: str, direction: int, stroke_progress: float,
                           depth: float = .5, width: float = 1.0
                           ) -> tuple[str, str, float]:
    """Return a smooth per-stroke morph into the neighbouring sequence."""
    if base_order not in ELECTRODE_ORDERS:
        base_order = ELECTRODE_ORDERS[0]
    index = ELECTRODE_ORDERS.index(base_order)
    target = ELECTRODE_ORDERS[(index + (1 if direction >= 0 else -1))
                              % len(ELECTRODE_ORDERS)]
    progress = min(1.0, max(0.0, stroke_progress))
    width = min(1.0, max(.1, width))
    distance = abs(progress - .5)
    if distance >= width / 2.0:
        envelope = 0.0
    else:
        envelope = (1.0 + math.cos(distance / (width / 2.0) * math.pi)) / 2.0
    return base_order, target, min(1.0, max(0.0, depth)) * envelope


def map_electrode_order(values: tuple[float, float, float, float], order: str
                        ) -> tuple[float, float, float, float]:
    """Map logical A-B-C-D path positions onto a physical electrode order."""
    if order not in ELECTRODE_ORDERS:
        order = "ABCD"
    mapped = [0.0] * 4
    for logical_index, physical_label in enumerate(order):
        mapped[ord(physical_label) - ord("A")] = values[logical_index]
    return tuple(mapped)


def morph_electrode_order(values: tuple[float, float, float, float], source: str,
                          destination: str, amount: float
                          ) -> tuple[float, float, float, float]:
    """Constant-energy morph between two signalling-sequence mappings."""
    amount = min(1.0, max(0.0, amount))
    start = map_electrode_order(values, source)
    end = map_electrode_order(values, destination)
    if amount == 0.0:
        return start
    if amount == 1.0:
        return end

    start_mean, end_mean = sum(start) / 4.0, sum(end) / 4.0
    start_vector = tuple(value - start_mean for value in start)
    end_vector = tuple(value - end_mean for value in end)
    start_norm = math.sqrt(sum(value * value for value in start_vector))
    end_norm = math.sqrt(sum(value * value for value in end_vector))
    if start_norm <= 1e-12 or end_norm <= 1e-12:
        return tuple(a + (b - a) * amount for a, b in zip(start, end))

    unit_start = tuple(value / start_norm for value in start_vector)
    unit_end = tuple(value / end_norm for value in end_vector)
    dot = min(1.0, max(-1.0, sum(a * b for a, b in zip(unit_start, unit_end))))
    if dot < -.999999:
        candidates = ((1.0, -1.0, 0.0, 0.0), (1.0, 0.0, -1.0, 0.0),
                      (1.0, 0.0, 0.0, -1.0))
        candidate = min(candidates,
                        key=lambda item: abs(sum(a * b for a, b in zip(unit_start, item))))
        projection = sum(a * b for a, b in zip(unit_start, candidate))
        orthogonal = tuple(value - projection * axis
                           for value, axis in zip(candidate, unit_start))
        orthogonal_norm = math.sqrt(sum(value * value for value in orthogonal))
        orthogonal = tuple(value / orthogonal_norm for value in orthogonal)
        direction = tuple(axis * math.cos(amount * math.pi)
                          + other * math.sin(amount * math.pi)
                          for axis, other in zip(unit_start, orthogonal))
    else:
        angle = math.acos(dot)
        if angle <= 1e-9:
            direction = unit_start
        else:
            denominator = math.sin(angle)
            start_weight = math.sin((1.0 - amount) * angle) / denominator
            end_weight = math.sin(amount * angle) / denominator
            direction = tuple(start_weight * a + end_weight * b
                              for a, b in zip(unit_start, unit_end))
    magnitude = start_norm + (end_norm - start_norm) * amount
    mean = start_mean + (end_mean - start_mean) * amount
    result = tuple(mean + magnitude * value for value in direction)
    low, high = min(result), max(result)
    if low < 0.0 or high > 1.0:
        span = high - low
        result = tuple((value - low) / span for value in result)
    return result


def pair_morph(values: tuple[float, float, float, float], amount: float
               ) -> tuple[float, float, float, float]:
    """Morph A<->B and C<->D without collapsing the differential midway.

    A straight interpolation makes both pairs equal at 50%, which can briefly
    remove the four-phase sensation.  Rotating the two pair differentials by
    180 degrees transfers their energy between pairs and preserves exact
    swapped endpoints.
    """
    amount = min(1.0, max(0.0, amount))
    a, b, c, d = values
    if amount == 0.0:
        return values
    if amount == 1.0:
        return (b, a, d, c)
    ab_mean, cd_mean = (a + b) / 2.0, (c + d) / 2.0
    ab_diff, cd_diff = (a - b) / 2.0, (c - d) / 2.0
    angle = amount * math.pi
    cosine, sine = math.cos(angle), math.sin(angle)
    rotated_ab = ab_diff * cosine - cd_diff * sine
    rotated_cd = ab_diff * sine + cd_diff * cosine

    # Retain the pair means and uniformly fit the rotated differential into
    # ReStim's 0..1 command range.  Uniform scaling preserves its direction.
    scale = 1.0
    for mean, difference in ((ab_mean, rotated_ab), (cd_mean, rotated_cd)):
        if difference > 0.0:
            scale = min(scale, (1.0 - mean) / difference, mean / difference)
        elif difference < 0.0:
            magnitude = -difference
            scale = min(scale, mean / magnitude, (1.0 - mean) / magnitude)
    scale = max(0.0, scale)
    rotated_ab *= scale
    rotated_cd *= scale
    return (ab_mean + rotated_ab, ab_mean - rotated_ab,
            cd_mean + rotated_cd, cd_mean - rotated_cd)


def vertical_crossfade(position: float) -> tuple[float, float, float, float]:
    """Visual-only A-to-D equal-power adjacent crossfade for a 0..1 position."""
    position = min(1.0, max(0.0, position))
    scaled = position * 3.0
    section = min(2, int(scaled))
    progress = scaled - section
    weights = [0.0, 0.0, 0.0, 0.0]
    weights[section] = math.cos(progress * math.pi / 2.0)
    weights[section + 1] = math.sin(progress * math.pi / 2.0)
    return tuple(weights)


def project_restim_intensities(
        values: tuple[float, float, float, float]
        ) -> tuple[float, float, float, float]:
    """Project apparent intensities into ReStim's valid four-phase domain.

    One requested intensity must equal one and the other three must total at
    least one.  A uniform normalization establishes the maximum; any remaining
    return deficit is distributed over the other channels in proportion to
    their available headroom.  This leaves already-valid profiles unchanged.
    """
    clamped = tuple(min(1.0, max(0.0, float(value))) for value in values)
    maximum = max(clamped)
    if maximum <= 1e-12:
        return (1.0, 1 / 3, 1 / 3, 1 / 3)
    normalized = [value / maximum for value in clamped]
    anchor = normalized.index(max(normalized))
    return_sum = sum(value for index, value in enumerate(normalized)
                     if index != anchor)
    deficit = max(0.0, 1.0 - return_sum)
    if deficit > 1e-12:
        headroom = sum(1.0 - value for index, value in enumerate(normalized)
                       if index != anchor)
        if headroom > 1e-12:
            for index, value in enumerate(normalized):
                if index != anchor:
                    normalized[index] = value + deficit * (1.0 - value) / headroom
    normalized[anchor] = 1.0
    return tuple(min(1.0, max(0.0, value)) for value in normalized)


def depth_spread(position: float, tip_retention: float = .80,
                 softness: float = .20, full_depth_capture: float = .05
                 ) -> tuple[float, float, float, float]:
    """Accumulate a logical A-to-D depth profile and project it for ReStim.

    B, C and D join over consecutive thirds of the L0 range.  ``softness``
    blends each linear join toward smoothstep without moving its endpoints.
    A stays fully present until D begins joining, then eases to
    ``tip_retention`` at full depth. ``full_depth_capture`` completes D early
    and holds the complete profile across the final portion of the depth range.
    """
    position = min(1.0, max(0.0, float(position)))
    retention = min(1.0, max(0.0, float(tip_retention)))
    softness = min(1.0, max(0.0, float(softness)))
    capture = min(.20, max(0.0, float(full_depth_capture)))

    def gate(local: float) -> float:
        if local >= 1.0 - 1e-12:
            return 1.0
        linear = min(1.0, max(0.0, local))
        smooth = linear * linear * (3.0 - 2.0 * linear)
        return linear + (smooth - linear) * softness

    b = gate(position * 3.0)
    c = gate(position * 3.0 - 1.0)
    # D still begins at two-thirds depth. Compress only its final ramp so full
    # depth can be reached by near-endpoint scripts without changing B or C.
    d = gate((position * 3.0 - 2.0) / (1.0 - 3.0 * capture))
    a = 1.0 - (1.0 - retention) * d
    return project_restim_intensities((a, b, c, d))


def directed_signed(position: float, direction: int = 1, return_depth: float = .30
                    ) -> tuple[tuple[float, float, float, float], int, int]:
    """Smooth adjacent-pair handover along A-B-C-D.

    In each section the first half reverses the adjacent source/return pair.
    The second half holds the destination primary while moving its return from
    the previous electrode to the next.  This avoids non-adjacent A->C roles.
    """
    position = min(1.0, max(0.0, position))
    return_depth = min(1.0, max(0.0, return_depth))
    scaled = position * 3.0

    def state(primary: int, preferred_return: int) -> tuple[float, ...]:
        values = [0.0, 0.0, 0.0, 0.0]
        values[primary] = 1.0
        values[preferred_return] = -return_depth
        return tuple(values)

    if direction >= 0:
        source = min(2, int(scaled))
        destination = source + 1
        progress = scaled - source
        incoming = source - 1 if source > 0 else destination
        outgoing = destination + 1 if destination < 3 else source
    else:
        source = max(1, min(3, math.ceil(scaled)))
        destination = source - 1
        progress = source - scaled
        incoming = source + 1 if source < 3 else destination
        outgoing = destination - 1 if destination > 0 else source

    if progress <= .5:
        start = state(source, destination)
        end = state(destination, source)
        local = progress * 2.0
        role_primary, role_return = source, destination
    else:
        start = state(destination, incoming)
        end = state(destination, outgoing)
        local = (progress - .5) * 2.0
        role_primary, role_return = destination, outgoing
    blend = (1.0 - math.cos(min(1.0, max(0.0, local)) * math.pi)) / 2.0
    values = tuple(a + (b - a) * blend for a, b in zip(start, end))
    return values, role_primary, role_return


def normalize_signed(values: tuple[float, float, float, float]
                     ) -> tuple[float, float, float, float]:
    """Map signed relative potentials into ReStim's 0..1 command range."""
    low, high = min(values), max(values)
    span = high - low
    if span <= 1e-12:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple((value - low) / span for value in values)


def _constrain_restim(values: tuple[float, float, float, float]
                      ) -> tuple[float, float, float, float]:
    """Scalar equivalent of ReStim constrain_4p_amplitudes."""
    a, b, c, d = (min(1.0, max(0.0, value)) for value in values)
    s_a = min(-a + b + c + d, 0.0) / -3.0
    s_b = min(a - b + c + d, 0.0) / -3.0
    s_c = min(a + b - c + d, 0.0) / -3.0
    s_d = min(a + b + c - d, 0.0) / -3.0
    result = [a + s_b + s_c + s_d, b + s_a + s_c + s_d,
              c + s_a + s_b + s_d, d + s_a + s_b + s_c]
    maximum = max(result)
    if maximum < 1.0:
        result = [value + 1.0 - maximum for value in result]
        result[result.index(max(result))] = 1.0
    return tuple(min(1.0, max(0.0, value)) for value in result)


def crossover_blend(progress: float, width: float = 1.0,
                    curve: str = "Cosine", sharpness: float = 1.0) -> float:
    """Shape one adjacent-electrode handover while preserving its endpoints."""
    progress = min(1.0, max(0.0, progress))
    width = min(1.0, max(.05, width))
    start = (1.0 - width) / 2.0
    local = min(1.0, max(0.0, (progress - start) / width))
    name = curve.strip().lower()
    if name == "linear":
        blend = local
    elif name == "ease in":
        blend = local * local
    elif name == "ease out":
        blend = 1.0 - (1.0 - local) ** 2
    elif name in ("s-curve", "s curve"):
        blend = local * local * (3.0 - 2.0 * local)
    else:
        blend = (1.0 - math.cos(local * math.pi)) / 2.0
    sharpness = min(5.0, max(.2, sharpness))
    if abs(sharpness - 1.0) > 1e-12 and 0.0 < blend < 1.0:
        high = blend ** sharpness
        low = (1.0 - blend) ** sharpness
        blend = high / (high + low)
    return blend


def restim_crossfade(position: float, direction: int = 1, return_depth: float = .30,
                     crossover_width: float = 1.0, curve: str = "Cosine",
                     sharpness: float = 1.0
                     ) -> tuple[float, float, float, float]:
    """Cross cell boundaries continuously in ReStim's own E1-E4 space."""
    position = min(1.0, max(0.0, position))
    depth = min(1.0, max(0.0, return_depth))
    neutral = depth / (1.0 + depth)

    def node(primary: int, preferred_return: int) -> tuple[float, ...]:
        values = [neutral] * 4
        values[primary], values[preferred_return] = 1.0, 0.0
        return tuple(values)

    scaled = position * 3.0
    if direction >= 0:
        section = min(2, int(scaled)); progress = scaled - section
        start = node(section, section + 1)
        end = node(section + 1, section + 2 if section < 2 else section)
    else:
        section = max(0, min(2, math.ceil(scaled) - 1)); progress = section + 1 - scaled
        start = node(section + 1, section)
        end = node(section, section - 1 if section > 0 else section + 1)
    blend = crossover_blend(progress, crossover_width, curve, sharpness)
    return _constrain_restim(tuple(a + (b - a) * blend for a, b in zip(start, end)))


def potential_roles(values: tuple[float, float, float, float], primary: int | None = None,
                    preferred_return: int | None = None) -> tuple[str, str]:
    labels = "ABCD"
    return (labels[primary if primary is not None else values.index(max(values))],
            labels[preferred_return if preferred_return is not None else values.index(min(values))])


def interpolate_electrodes(
        history: list[tuple[float, tuple[float, float, float, float]]],
        target_time: float) -> tuple[float, float, float, float]:
    """Interpolate a four-electrode history without extrapolating its endpoints."""
    if not history:
        return (.5, .5, .5, .5)
    if target_time <= history[0][0]:
        return history[0][1]
    if target_time >= history[-1][0]:
        return history[-1][1]
    for (left_time, left), (right_time, right) in zip(history, history[1:]):
        if target_time <= right_time:
            span = right_time - left_time
            amount = 0.0 if span <= 1e-12 else (target_time - left_time) / span
            return tuple(a + (b - a) * amount for a, b in zip(left, right))
    return history[-1][1]


def apply_group_delay(
        current: tuple[float, float, float, float],
        history: list[tuple[float, tuple[float, float, float, float]]],
        at_time: float, signed_delay_seconds: float
        ) -> tuple[float, float, float, float]:
    """Delay A/B when positive or C/D when negative, preserving the other group."""
    if abs(signed_delay_seconds) <= 1e-9 or not history:
        return current
    delayed = interpolate_electrodes(history, at_time - abs(signed_delay_seconds))
    if signed_delay_seconds > 0:
        return delayed[0], delayed[1], current[2], current[3]
    return current[0], current[1], delayed[2], delayed[3]
