"""Live funscript-tools custom events on Vector's delayed media timeline.

Stdlib-only YAML subset loader (no PyYAML). Matches offline Event Builder
semantics for supported axes: volume, volume-prostate, pulse_frequency,
pulse_width, frequency, alpha, beta, e1–e4, sensor_suppression. Extract
composites bake hub–spoke motion at expand time via extract_composite
(SCD ~dur or L0 beat-sync siblings).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import threading
from typing import Any, Sequence

from .extract_composite import (
    EXTRACT_BEAT_EVENTS,
    build_extract_motion_steps,
    derive_extract_params,
)

SUPPORTED_AXES = frozenset({
    "volume",
    "volume-prostate",
    "pulse_frequency",
    "pulse_width",
    "frequency",
    "alpha",
    "beta",
    "e1",
    "e2",
    "e3",
    "e4",
    "sensor_suppression",
})

AXIS_AUTHORED = {
    "volume": "V0",
    "frequency": "C0",
    "pulse_frequency": "P0",
    "pulse_width": "P1",
    "alpha": "L0",
    "beta": "L1",
    "e1": "E1",
    "e2": "E2",
    "e3": "E3",
    "e4": "E4",
    "sensor_suppression": "S1",
}

DEFAULT_NORMALIZATION = {
    "pulse_frequency": {"max": 200.0},
    "pulse_width": {"max": 100.0},
    "frequency": {"max": 360.0},
    "volume": {"max": 1.0},
    "sensor_suppression": {"max": 100.0},
}

_BUNDLED_DEFINITIONS = Path(__file__).with_name("event_definitions.yml")


class EventError(Exception):
    """Raised for load/parse failures that abort event loading."""


# ---------------------------------------------------------------------------
# Minimal YAML subset (maps, lists, scalars, comments)
# ---------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index].rstrip()
    return line.rstrip()


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (
            text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "~"):
        return None
    try:
        if any(char in text for char in ".eE") and text.replace(".", "", 1).replace(
                "-", "", 1).replace("+", "", 1).replace("e", "", 1).replace(
                "E", "", 1).isdigit() is False:
            # fall through to float attempt
            pass
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_yaml_subset(text: str) -> Any:
    """Parse a restricted YAML subset used by event definition / user files."""
    raw_lines = text.splitlines()
    lines: list[tuple[int, str]] = []
    for raw in raw_lines:
        cleaned = _strip_comment(raw)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        lines.append((indent, cleaned.strip()))

    index = 0

    def parse_block(min_indent: int) -> Any:
        nonlocal index
        if index >= len(lines):
            return None
        indent, content = lines[index]
        if indent < min_indent:
            return None
        if content.startswith("- "):
            return parse_list(min_indent)
        if ":" in content:
            return parse_map(min_indent)
        value = _parse_scalar(content)
        index += 1
        return value

    def parse_map(min_indent: int) -> dict[str, Any]:
        nonlocal index
        result: dict[str, Any] = {}
        while index < len(lines):
            indent, content = lines[index]
            if indent < min_indent:
                break
            if content.startswith("- "):
                break
            if indent > min_indent and result:
                break
            if ":" not in content:
                raise EventError(f"Expected mapping entry, got: {content}")
            key, _, remainder = content.partition(":")
            key = key.strip()
            remainder = remainder.strip()
            index += 1
            if remainder:
                result[key] = _parse_scalar(remainder)
            else:
                if index >= len(lines):
                    result[key] = None
                    continue
                next_indent, next_content = lines[index]
                # YAML allows a sequence value at the same indent as the key:
                #   events:
                #   - time: 0
                if next_content.startswith("- ") and next_indent <= indent:
                    result[key] = parse_list(next_indent)
                elif next_indent <= indent:
                    result[key] = None
                elif next_content.startswith("- "):
                    result[key] = parse_list(next_indent)
                else:
                    result[key] = parse_map(next_indent)
        return result

    def parse_list(min_indent: int) -> list[Any]:
        nonlocal index
        result: list[Any] = []
        while index < len(lines):
            indent, content = lines[index]
            if indent < min_indent:
                break
            if not content.startswith("- "):
                break
            if indent > min_indent and result:
                break
            item_text = content[2:].strip()
            index += 1
            if not item_text:
                if index < len(lines) and lines[index][0] > indent:
                    child_indent = lines[index][0]
                    if lines[index][1].startswith("- "):
                        result.append(parse_list(child_indent))
                    else:
                        result.append(parse_map(child_indent))
                else:
                    result.append(None)
            elif item_text.endswith(":") and ":" == item_text[-1]:
                # "- key:" with nested map, or "- key: value" already handled
                key = item_text[:-1].strip()
                nested: dict[str, Any] = {}
                if index < len(lines) and lines[index][0] > indent:
                    nested = parse_map(lines[index][0])
                nested_prefix = {key: None}
                # Actually "- name: value" form is more common
                result.append(nested if nested else {key: None})
            elif ":" in item_text and not item_text.startswith("{"):
                # Inline mapping start: "- operation: apply_linear_change"
                key, _, remainder = item_text.partition(":")
                entry: dict[str, Any] = {key.strip(): _parse_scalar(remainder.strip())}
                if index < len(lines) and lines[index][0] > indent:
                    entry.update(parse_map(lines[index][0]))
                result.append(entry)
            else:
                result.append(_parse_scalar(item_text))
        return result

    if not lines:
        return None
    return parse_block(lines[0][0])


def load_yaml_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EventError(f"Failed to read {path}: {exc}") from exc
    try:
        return parse_yaml_subset(text)
    except EventError:
        raise
    except Exception as exc:
        raise EventError(f"Failed to parse YAML {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Definitions + user event expansion
# ---------------------------------------------------------------------------

def _derive_step_ratio_params(final_params: dict[str, Any], event_name: str) -> None:
    if "step_ratio" not in final_params:
        return
    sr = float(final_params["step_ratio"])
    if not (0 < sr < 1 / 3):
        raise EventError(
            f"Event '{event_name}': step_ratio must be in (0, 1/3), got {sr}")
    final_params.update({
        "e3_phase": (1 - sr) * 360,
        "e2_phase": (1 - 2 * sr) * 360,
        "e1_duty": 1 - 3 * sr,
        "e1_phase": (1 - 3 * sr) * 360,
        "e3_tri_phase": (0.5 - sr) * 360,
        "e2_tri_phase": (0.5 - 2 * sr) * 360,
    })


# Design defaults for orgasm countdown stretch (lead-in + fade stay fixed).
_ORGASM_COUNTDOWN_EVENTS = frozenset({
    "mcb_orgasm_countdown",
    "mcb_orgasm_countdown_stroke_override",
})
_ORGASM_BASE_SEG_MS = 25867.0   # default orgasm enable → fade
_ORGASM_BASE_GOODBOY_MS = 5000.0


def _derive_orgasm_countdown_params(final_params: dict[str, Any],
                                    event_name: str) -> None:
    """When duration stretches, extend climax (amp9) and scale goodBoy with it.

    Lead-in offsets (countdown, goodBoy start) and fade ramp stay at YAML defaults.
    seg_orgasm_ms = duration_ms - orgasm_offset_ms
    goodboy_duration_ms = max(5000, 5000 × seg_orgasm_ms / 25867)
    """
    if event_name not in _ORGASM_COUNTDOWN_EVENTS:
        return

    try:
        duration_ms = float(final_params.get("duration_ms", 0))
        orgasm_offset_ms = float(final_params.get("orgasm_offset_ms", 21000))
        ramp_ms = float(final_params.get("ramp_ms", 1500))
    except (TypeError, ValueError) as exc:
        raise EventError(
            f"Event '{event_name}': invalid duration/orgasm_offset/ramp "
            f"params: {exc}"
        ) from exc

    min_duration = orgasm_offset_ms + max(ramp_ms, 1.0)
    if duration_ms < min_duration:
        raise EventError(
            f"Event '{event_name}': duration_ms ({duration_ms:g}) must be at "
            f"least orgasm_offset_ms + ramp_ms ({min_duration:g})."
        )

    seg_orgasm_ms = duration_ms - orgasm_offset_ms
    scale = seg_orgasm_ms / _ORGASM_BASE_SEG_MS
    goodboy_duration_ms = max(
        _ORGASM_BASE_GOODBOY_MS, _ORGASM_BASE_GOODBOY_MS * scale)

    final_params["seg_orgasm_ms"] = int(round(seg_orgasm_ms))
    final_params["goodboy_duration_ms"] = int(round(goodboy_duration_ms))


def _substitute_token(value: Any, final_params: dict[str, Any],
                      event_name: str) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        token = value[1:]
        if token not in final_params:
            raise EventError(
                f"Token '{token}' not found in params for event '{event_name}'.")
        return final_params[token]
    return value


def normalize_value(axis: str, value: float,
                    normalization: dict[str, dict[str, float]]) -> float:
    """Normalize raw axis units to 0..1 using definition max (funscript-tools rules)."""
    for axis_key, config in normalization.items():
        if axis_key in axis:
            max_value = float(config.get("max", 1.0))
            if max_value == 1.0:
                return float(value)
            if max_value > 1.0 and 0.0 <= float(value) <= 1.0:
                return float(value)
            return float(value) / max_value
    return float(value)


def _waveform_value(waveform: str, relative_time_s: float, frequency: float,
                    phase_deg: float, duty_cycle: float) -> float:
    phase_normalized = (phase_deg / 360.0) % 1.0
    waveform_phase = (frequency * relative_time_s + phase_normalized) % 1.0
    kind = waveform.lower()
    if kind == "sin":
        return math.sin(2 * math.pi * frequency * relative_time_s
                        + math.radians(phase_deg))
    if kind == "square":
        clipped = min(0.99, max(0.01, duty_cycle))
        return 1.0 if waveform_phase < clipped else -1.0
    if kind == "triangle":
        if waveform_phase < 0.5:
            return -1.0 + 4.0 * waveform_phase
        return 3.0 - 4.0 * waveform_phase
    if kind == "sawtooth":
        return -1.0 + 2.0 * waveform_phase
    raise EventError(f"Unsupported waveform '{waveform}'")


def _ramp_envelope(relative_time_s: float, duration_s: float,
                   ramp_in_s: float, ramp_out_s: float) -> float:
    if duration_s <= 0:
        return 1.0
    envelope = 1.0
    if ramp_in_s > 0:
        ramp_in_end = min(ramp_in_s, duration_s)
        if relative_time_s < ramp_in_end:
            envelope *= relative_time_s / ramp_in_end if ramp_in_end > 0 else 1.0
    if ramp_out_s > 0:
        ramp_out_start = duration_s - min(ramp_out_s, duration_s)
        if relative_time_s > ramp_out_start:
            span = duration_s - ramp_out_start
            if span > 0:
                envelope *= max(0.0, (duration_s - relative_time_s) / span)
    return envelope


def _overwrite_blend(relative_time_s: float, duration_s: float,
                     ramp_in_s: float, ramp_out_s: float) -> float:
    """Return blend 0..1 from original→effect for overwrite mode."""
    if duration_s <= 0:
        return 1.0
    blend = 1.0
    if ramp_in_s > 0:
        ramp_in_end = min(ramp_in_s, duration_s)
        if relative_time_s < ramp_in_end:
            blend = relative_time_s / ramp_in_end if ramp_in_end > 0 else 1.0
    if ramp_out_s > 0:
        ramp_out_start = duration_s - min(ramp_out_s, duration_s)
        if relative_time_s > ramp_out_start:
            span = duration_s - ramp_out_start
            if span > 0:
                blend = max(0.0, (duration_s - relative_time_s) / span)
    return blend


@dataclass(frozen=True)
class ActiveStep:
    """One expanded, axis-resolved operation ready for single-sample eval."""
    event_name: str
    operation: str
    axis: str
    start_time_ms: int
    duration_ms: int
    params: dict[str, Any]


@dataclass
class LoadedEvents:
    steps: list[ActiveStep] = field(default_factory=list)
    event_count: int = 0
    warnings: list[str] = field(default_factory=list)
    source_path: str = ""


@dataclass
class ScheduledTrigger:
    """One live EVT instance scheduled onto the send/due_at clock."""
    name: str
    activate_at: float
    steps: list[ActiveStep]
    duration_ms: int
    warnings: list[str] = field(default_factory=list)


def load_definitions(path: Path | None = None
                     ) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    definitions_path = Path(path) if path else _BUNDLED_DEFINITIONS
    data = load_yaml_file(definitions_path)
    if not isinstance(data, dict) or "definitions" not in data:
        raise EventError(
            "Event definitions file must contain a top-level 'definitions' key.")
    definitions = data["definitions"]
    if not isinstance(definitions, dict):
        raise EventError("'definitions' must be a mapping.")
    normalization = data.get("normalization") or dict(DEFAULT_NORMALIZATION)
    if not isinstance(normalization, dict):
        raise EventError("'normalization' must be a mapping.")
    # Ensure nested max defaults
    merged = {key: dict(value) for key, value in DEFAULT_NORMALIZATION.items()}
    for key, value in normalization.items():
        if isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
    return definitions, merged


def _append_resolved_step(
        expanded: list[ActiveStep],
        unsupported_seen: set[str],
        *,
        event_name: str,
        step: dict[str, Any],
        step_idx: int,
        final_params: dict[str, Any],
        event_time_ms: int,
        substitute: bool,
) -> None:
    """Resolve one YAML/motion step dict into ActiveSteps (axis-split)."""
    if "operation" not in step:
        raise EventError(
            f"Event '{event_name}': step {step_idx} is missing 'operation'.")
    if "axis" not in step:
        raise EventError(
            f"Event '{event_name}': step {step_idx} is missing 'axis'.")
    operation = step["operation"]
    step_params_raw = dict(step.get("params") or {})
    if (operation == "apply_linear_change"
            and "start_value" not in step_params_raw):
        raise EventError(
            f"Event '{event_name}': step {step_idx} uses "
            f"'apply_linear_change' but is missing 'start_value'.")

    if substitute:
        processed_params = {
            key: _substitute_token(value, final_params, event_name)
            for key, value in step_params_raw.items()
        }
        start_offset = _substitute_token(
            step.get("start_offset", 0), final_params, event_name)
    else:
        processed_params = dict(step_params_raw)
        start_offset = step.get("start_offset", 0)
    try:
        start_offset_ms = int(start_offset)
    except (TypeError, ValueError) as exc:
        raise EventError(
            f"Event '{event_name}': invalid start_offset") from exc

    axis_field = str(step["axis"])
    for axis_name in [name.strip() for name in axis_field.split(",")]:
        if not axis_name:
            continue
        if axis_name not in SUPPORTED_AXES:
            unsupported_seen.add(axis_name)
            continue
        try:
            duration_ms = int(processed_params["duration_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EventError(
                f"Event '{event_name}': step needs duration_ms") from exc
        expanded.append(ActiveStep(
            event_name=event_name,
            operation=str(operation),
            axis=axis_name,
            start_time_ms=event_time_ms + start_offset_ms,
            duration_ms=duration_ms,
            params=dict(processed_params),
        ))


def resolve_l0_funscript_path(events_path: Path) -> Path | None:
    """Companion L0 stroke next to ``*.events.yml`` (same rules as funscript-tools)."""
    name = events_path.name
    base = name
    for suffix in (".events.yml", ".events.yaml"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    parent = events_path.parent
    for candidate in (
        parent / f"{base}.funscript",
        parent / f"{base}.L0.funscript",
        parent / f"{base}.l0.funscript",
        parent / "L0.funscript",
        parent / "l0.funscript",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_l0_series(path: Path | str) -> tuple[list[float], list[float]]:
    """Load funscript actions as (times_s, values_0_1)."""
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions") or []
    if not isinstance(actions, list):
        raise EventError(f"Funscript '{path}' actions must be a list.")
    sorted_actions = sorted(
        (a for a in actions if isinstance(a, dict) and "at" in a and "pos" in a),
        key=lambda a: float(a["at"]),
    )
    times_s = [float(a["at"]) / 1000.0 for a in sorted_actions]
    values = [float(a["pos"]) * 0.01 for a in sorted_actions]
    return times_s, values


def expand_named_event(
        event_name: str,
        params: dict[str, Any] | None,
        definitions: dict[str, Any],
        *,
        event_time_ms: int = 0,
        l0_times_s: Sequence[float] | None = None,
        l0_values: Sequence[float] | None = None,
        warn_missing_l0: bool = False,
) -> tuple[list[ActiveStep], list[str]]:
    """Expand one named definition into ActiveSteps (relative to *event_time_ms*)."""
    if event_name not in definitions:
        raise EventError(
            f"Event '{event_name}' is not defined in event_definitions.yml.")
    definition = definitions[event_name]
    if not isinstance(definition, dict):
        raise EventError(f"Definition for '{event_name}' must be a mapping.")

    final_params = dict(definition.get("default_params") or {})
    if params:
        final_params.update(params)
    _derive_step_ratio_params(final_params, event_name)
    _derive_orgasm_countdown_params(final_params, event_name)
    try:
        derive_extract_params(final_params, event_name)
    except ValueError as exc:
        raise EventError(str(exc)) from exc

    expanded: list[ActiveStep] = []
    unsupported_seen: set[str] = set()
    warnings: list[str] = []

    for step_idx, step in enumerate(definition.get("steps") or [], start=1):
        if not isinstance(step, dict):
            raise EventError(
                f"Event '{event_name}': step {step_idx} must be a mapping.")
        _append_resolved_step(
            expanded, unsupported_seen,
            event_name=event_name,
            step=step,
            step_idx=step_idx,
            final_params=final_params,
            event_time_ms=event_time_ms,
            substitute=True,
        )

    motion_kwargs: dict[str, Any] = {}
    if event_name in EXTRACT_BEAT_EVENTS:
        motion_kwargs = {
            "l0_times_s": l0_times_s,
            "l0_values": l0_values,
            "event_start_ms": event_time_ms,
        }
        if (
            warn_missing_l0
            and l0_times_s is None
            and final_params.get("switch_offsets_ms") is None
        ):
            warnings.append(
                f"Event '{event_name}' has no L0 funscript and no "
                "switch_offsets_ms; pole dwells fall back to SCD ~dur."
            )
    motion_steps = build_extract_motion_steps(
        final_params, event_name, **motion_kwargs)
    shell_count = len(definition.get("steps") or [])
    for motion_idx, step in enumerate(motion_steps, start=1):
        if not isinstance(step, dict):
            raise EventError(
                f"Event '{event_name}': motion step {motion_idx} must be a mapping.")
        _append_resolved_step(
            expanded, unsupported_seen,
            event_name=event_name,
            step=step,
            step_idx=shell_count + motion_idx,
            final_params=final_params,
            event_time_ms=event_time_ms,
            substitute=False,
        )

    if unsupported_seen:
        warnings.append(
            "Skipped unsupported axis steps: "
            + ", ".join(sorted(unsupported_seen))
            + f" (supported: {', '.join(sorted(SUPPORTED_AXES))})")
    return expanded, warnings


def expand_user_events(
        user_data: dict[str, Any],
        definitions: dict[str, Any],
        *,
        l0_times_s: Sequence[float] | None = None,
        l0_values: Sequence[float] | None = None,
        warn_missing_l0: bool = False,
) -> LoadedEvents:
    """Parse user events mapping; drop unsupported-axis steps with warnings."""
    if "events" not in user_data:
        raise EventError("User event file must contain a top-level 'events' key.")
    user_events = user_data["events"]
    if not isinstance(user_events, list):
        raise EventError("'events' key in user file must contain a list.")

    result = LoadedEvents()
    expanded: list[ActiveStep] = []
    warning_set: set[str] = set()

    for index, user_event in enumerate(user_events):
        if not isinstance(user_event, dict):
            raise EventError(f"Event #{index + 1} must be a mapping.")
        if "time" not in user_event or "name" not in user_event:
            raise EventError(
                f"Event #{index + 1} is missing required key: 'time' or 'name'.")
        event_name = str(user_event["name"])
        time_raw = user_event["time"]
        if not isinstance(time_raw, (int, float)):
            raise EventError(
                f"Event '{event_name}' has invalid 'time' (must be number ms).")
        event_time_ms = int(time_raw)
        params = user_event["params"] if isinstance(
            user_event.get("params"), dict) else None
        try:
            steps, warnings = expand_named_event(
                event_name,
                params,
                definitions,
                event_time_ms=event_time_ms,
                l0_times_s=l0_times_s,
                l0_values=l0_values,
                warn_missing_l0=warn_missing_l0,
            )
        except EventError as exc:
            if event_name not in definitions:
                raise EventError(
                    f"Event '{event_name}' at time {event_time_ms} "
                    f"is not defined in event_definitions.yml.") from exc
            raise
        expanded.extend(steps)
        warning_set.update(warnings)

    result.warnings.extend(sorted(warning_set))
    expanded.sort(key=lambda step: (step.start_time_ms, step.event_name, step.axis))
    result.steps = expanded
    result.event_count = len(user_events)
    return result


def apply_linear_change(base: float, position_ms: int, start_time_ms: int,
                        duration_ms: int, start_value: float, end_value: float,
                        ramp_in_ms: int = 0, ramp_out_ms: int = 0,
                        mode: str = "additive",
                        axis: str = "volume",
                        normalization: dict[str, dict[str, float]] | None = None,
                        ) -> float:
    """Single-sample linear change matching FunscriptEditor semantics."""
    norm = normalization or DEFAULT_NORMALIZATION
    if duration_ms < 0:
        return base
    if position_ms < start_time_ms:
        return base
    if duration_ms == 0:
        if position_ms != start_time_ms:
            return base
        effect = normalize_value(axis, start_value, norm)
        if mode == "overwrite":
            return min(1.0, max(0.0, effect))
        return min(1.0, max(0.0, base + effect))
    end_time_ms = start_time_ms + duration_ms
    if position_ms >= end_time_ms:
        return base

    duration_s = duration_ms / 1000.0
    relative_time_s = (position_ms - start_time_ms) / 1000.0
    progress = relative_time_s / duration_s if duration_s > 0 else 0.0
    start_n = normalize_value(axis, start_value, norm)
    end_n = normalize_value(axis, end_value, norm)
    linear = start_n + (end_n - start_n) * progress
    ramp_in_s = ramp_in_ms / 1000.0
    ramp_out_s = ramp_out_ms / 1000.0

    if mode == "additive":
        envelope = _ramp_envelope(relative_time_s, duration_s, ramp_in_s, ramp_out_s)
        return min(1.0, max(0.0, base + linear * envelope))
    if mode == "overwrite":
        blend = _overwrite_blend(relative_time_s, duration_s, ramp_in_s, ramp_out_s)
        return min(1.0, max(0.0, (1.0 - blend) * base + blend * linear))
    return base


def apply_modulation(base: float, position_ms: int, start_time_ms: int,
                     duration_ms: int, waveform: str, frequency: float,
                     amplitude: float, max_level_offset: float = 0.0,
                     phase: float = 0.0, ramp_in_ms: int = 0,
                     ramp_out_ms: int = 0, mode: str = "additive",
                     duty_cycle: float = 0.5, axis: str = "volume",
                     normalization: dict[str, dict[str, float]] | None = None,
                     ) -> float:
    """Single-sample modulation (v2.2.5 DC-center semantics)."""
    norm = normalization or DEFAULT_NORMALIZATION
    if duration_ms <= 0:
        return base
    if position_ms < start_time_ms or position_ms >= start_time_ms + duration_ms:
        return base

    duration_s = duration_ms / 1000.0
    relative_time_s = (position_ms - start_time_ms) / 1000.0
    try:
        base_wave = _waveform_value(waveform, relative_time_s, float(frequency),
                                    float(phase), float(duty_cycle))
    except EventError:
        return base

    amp_n = normalize_value(axis, amplitude, norm)
    offset_n = normalize_value(axis, max_level_offset, norm)
    generated = offset_n + amp_n * base_wave
    ramp_in_s = ramp_in_ms / 1000.0
    ramp_out_s = ramp_out_ms / 1000.0

    if mode == "additive":
        envelope = _ramp_envelope(relative_time_s, duration_s, ramp_in_s, ramp_out_s)
        return min(1.0, max(0.0, base + generated * envelope))
    if mode == "overwrite":
        blend = _overwrite_blend(relative_time_s, duration_s, ramp_in_s, ramp_out_s)
        return min(1.0, max(0.0, (1.0 - blend) * base + blend * generated))
    return base


def evaluate_step(base: float, position_ms: int, step: ActiveStep,
                  normalization: dict[str, dict[str, float]]) -> float:
    params = step.params
    if step.operation == "apply_linear_change":
        return apply_linear_change(
            base, position_ms, step.start_time_ms, step.duration_ms,
            float(params["start_value"]),
            float(params.get("end_value", params["start_value"])),
            int(params.get("ramp_in_ms", 0) or 0),
            int(params.get("ramp_out_ms", 0) or 0),
            str(params.get("mode", "additive")),
            step.axis,
            normalization,
        )
    if step.operation == "apply_modulation":
        return apply_modulation(
            base, position_ms, step.start_time_ms, step.duration_ms,
            str(params["waveform"]),
            float(params["frequency"]),
            float(params["amplitude"]),
            float(params.get("max_level_offset", 0.0) or 0.0),
            float(params.get("phase", 0.0) or 0.0),
            int(params.get("ramp_in_ms", 0) or 0),
            int(params.get("ramp_out_ms", 0) or 0),
            str(params.get("mode", "additive")),
            float(params.get("duty_cycle", 0.5) or 0.5),
            step.axis,
            normalization,
        )
    return base


class EventEngine:
    """Load definitions + `.events.yml` and evaluate supported axes per sample."""

    def __init__(self, definitions_path: Path | str | None = None) -> None:
        self.definitions_path = Path(definitions_path) if definitions_path else _BUNDLED_DEFINITIONS
        self.definitions: dict[str, Any] = {}
        self.normalization: dict[str, dict[str, float]] = dict(DEFAULT_NORMALIZATION)
        self.loaded = LoadedEvents()
        self._load_error = ""
        self._trigger_lock = threading.Lock()
        self._triggers: list[ScheduledTrigger] = []
        self._trigger_warnings: list[str] = []
        try:
            self.reload_definitions()
        except EventError as exc:
            self._load_error = str(exc)

    def reload_definitions(self, path: Path | str | None = None) -> None:
        if path is not None:
            self.definitions_path = Path(path)
        self.definitions, self.normalization = load_definitions(self.definitions_path)
        self._load_error = ""

    def load_events_file(self, path: Path | str) -> LoadedEvents:
        events_path = Path(path)
        data = load_yaml_file(events_path)
        if not isinstance(data, dict):
            raise EventError("User event file root must be a mapping.")
        if not self.definitions:
            self.reload_definitions()
        l0_times_s: list[float] | None = None
        l0_values: list[float] | None = None
        l0_path = resolve_l0_funscript_path(events_path)
        if l0_path is not None:
            l0_times_s, l0_values = load_l0_series(l0_path)
        loaded = expand_user_events(
            data,
            self.definitions,
            l0_times_s=l0_times_s,
            l0_values=l0_values,
            warn_missing_l0=True,
        )
        loaded.source_path = str(events_path)
        self.loaded = loaded
        self._load_error = ""
        return loaded

    def clear(self) -> None:
        self.loaded = LoadedEvents()
        self._load_error = ""
        self.clear_triggers()

    def clear_triggers(self) -> None:
        with self._trigger_lock:
            self._triggers.clear()
            self._trigger_warnings.clear()

    @property
    def warnings(self) -> list[str]:
        with self._trigger_lock:
            trigger_warns = list(self._trigger_warnings)
        return list(self.loaded.warnings) + trigger_warns

    @property
    def event_count(self) -> int:
        return self.loaded.event_count

    @property
    def step_count(self) -> int:
        return len(self.loaded.steps)

    @property
    def pending_trigger_count(self) -> int:
        with self._trigger_lock:
            return len(self._triggers)

    def schedule_trigger(self, name: str, params: dict[str, Any] | None,
                         activate_at: float) -> bool:
        """Expand and queue a live trigger. Returns False if expand failed."""
        if not self.definitions:
            try:
                self.reload_definitions()
            except EventError as exc:
                with self._trigger_lock:
                    self._trigger_warnings.append(str(exc))
                return False
        try:
            steps, warnings = expand_named_event(
                str(name), params or {}, self.definitions, event_time_ms=0)
        except EventError as exc:
            with self._trigger_lock:
                self._trigger_warnings.append(str(exc))
                if len(self._trigger_warnings) > 20:
                    self._trigger_warnings = self._trigger_warnings[-20:]
            return False
        duration_ms = 0
        for step in steps:
            duration_ms = max(duration_ms, step.start_time_ms + max(0, step.duration_ms))
        trigger = ScheduledTrigger(
            name=str(name),
            activate_at=float(activate_at),
            steps=steps,
            duration_ms=duration_ms,
            warnings=list(warnings),
        )
        with self._trigger_lock:
            self._triggers.append(trigger)
            for warning in warnings:
                if warning not in self._trigger_warnings:
                    self._trigger_warnings.append(warning)
        return True

    def apply(self, position_ms: int | None,
              values: dict[str, float]) -> dict[str, float]:
        """Apply active file steps in file order; clip each axis to 0..1.

        Returns a new dict. Inactive when *position_ms* is None.
        """
        if position_ms is None or not self.loaded.steps:
            return dict(values)
        result = {axis: float(value) for axis, value in values.items()}
        for step in self.loaded.steps:
            if step.axis not in result:
                continue
            end = step.start_time_ms + max(0, step.duration_ms)
            if step.duration_ms == 0:
                if position_ms != step.start_time_ms:
                    continue
            elif position_ms < step.start_time_ms or position_ms >= end:
                continue
            result[step.axis] = evaluate_step(
                result[step.axis], position_ms, step, self.normalization)
        return result

    def apply_triggers(self, due_at: float,
                       values: dict[str, float]) -> dict[str, float]:
        """Apply scheduled triggers whose windows cover *due_at*; prune expired."""
        result = {axis: float(value) for axis, value in values.items()}
        with self._trigger_lock:
            alive: list[ScheduledTrigger] = []
            for trigger in self._triggers:
                end_at = trigger.activate_at + (trigger.duration_ms / 1000.0)
                if due_at >= end_at and trigger.duration_ms > 0:
                    continue
                if due_at >= end_at and trigger.duration_ms == 0:
                    # Instant triggers only fire at the activate sample.
                    if abs(due_at - trigger.activate_at) > 1e-9:
                        continue
                alive.append(trigger)
                if due_at < trigger.activate_at:
                    continue
                elapsed_ms = int(round((due_at - trigger.activate_at) * 1000.0))
                for step in trigger.steps:
                    if step.axis not in result:
                        continue
                    end = step.start_time_ms + max(0, step.duration_ms)
                    if step.duration_ms == 0:
                        if elapsed_ms != step.start_time_ms:
                            continue
                    elif elapsed_ms < step.start_time_ms or elapsed_ms >= end:
                        continue
                    result[step.axis] = evaluate_step(
                        result[step.axis], elapsed_ms, step, self.normalization)
            self._triggers = alive
        return result

    def active_event_names(self, position_ms: int | None) -> list[str]:
        if position_ms is None:
            return []
        names: list[str] = []
        seen: set[str] = set()
        for step in self.loaded.steps:
            end = step.start_time_ms + max(0, step.duration_ms)
            active = (position_ms == step.start_time_ms if step.duration_ms == 0
                      else step.start_time_ms <= position_ms < end)
            if active and step.event_name not in seen:
                seen.add(step.event_name)
                names.append(step.event_name)
        return names

    def active_trigger_names(self, due_at: float | None) -> list[str]:
        if due_at is None:
            return []
        names: list[str] = []
        seen: set[str] = set()
        with self._trigger_lock:
            for trigger in self._triggers:
                if due_at < trigger.activate_at:
                    continue
                end_at = trigger.activate_at + (trigger.duration_ms / 1000.0)
                if trigger.duration_ms > 0 and due_at >= end_at:
                    continue
                if trigger.duration_ms == 0 and abs(due_at - trigger.activate_at) > 1e-9:
                    continue
                if trigger.name not in seen:
                    seen.add(trigger.name)
                    names.append(trigger.name)
        return names

    def status_line(self, position_ms: int | None = None,
                    enabled: bool = True,
                    due_at: float | None = None) -> str:
        if self._load_error:
            return f"Events: error — {self._load_error}"
        if not enabled:
            return "Events: off"
        with self._trigger_lock:
            pending = len(self._triggers)
            trigger_warn = self._trigger_warnings[0] if self._trigger_warnings else ""
        active_triggers = self.active_trigger_names(due_at)
        trigger_bit = ""
        if active_triggers:
            trigger_bit = f"triggers={', '.join(active_triggers)}"
        elif pending:
            trigger_bit = f"triggers pending={pending}"

        if not self.loaded.source_path:
            if trigger_bit:
                warn = f"; {trigger_warn}" if trigger_warn else ""
                return f"Events: {trigger_bit}{warn}"
            return "Events: no file loaded (EVT triggers ok)"
        active = self.active_event_names(position_ms)
        warn = f"; {self.loaded.warnings[0]}" if self.loaded.warnings else ""
        if not warn and trigger_warn:
            warn = f"; {trigger_warn}"
        file_bit = f"{self.loaded.event_count} loaded, {self.step_count} steps"
        if position_ms is None:
            base = f"Events: {file_bit} (no media position)"
        elif active:
            base = (f"Events: {file_bit}, active={', '.join(active)} "
                    f"@ {position_ms} ms")
        else:
            base = f"Events: {file_bit}, idle @ {position_ms} ms"
        if trigger_bit:
            return f"{base}; {trigger_bit}{warn}"
        return f"{base}{warn}"
