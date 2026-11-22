"""Editable, offline VacuGlide timelines and Autoblow instruction import."""
from bisect import bisect_right
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from html import unescape
import json
import math
from pathlib import Path
import re
from statistics import median
import tempfile


MAX_MS = 24 * 60 * 60 * 1000
KINDS = ("speed", "minus", "plus")
LABELS = {"speed": "Speed", "minus": "Stroke -", "plus": "Stroke +"}
TIME = r"\d+(?::[0-5]\d){1,2}(?:\.\d{1,3})?"
INTERVAL = rf"{TIME}(?![\d:.])|Instant|<\s*1\s*(?:seconds?|secs?|s)\b|(?:\d+\s*h\s*)?(?:\d+\s*m\s*)?\d+(?:\.\d+)?\s*s|\d+\s*h(?:\s*\d+\s*m)?|\d+\s*m"
ACTION = r"Speed\s+\d+(?:\.\d+)?\s*%|Stroke\s+(?:Minus|Plus|[+−-])\s+(?:Open|Closed)"
ROW = re.compile(rf"(?P<action>{ACTION})\s+at\s+(?P<time>{TIME})\s+(?P<interval>{INTERVAL})", re.I)
ACTION_LINE = re.compile(rf"(?:^|\n)\s*(?:(?P<ordinal>\d+)\s+)?(?P<action>{ACTION})", re.I)


def to_ms(value):
    return int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def parse_time(text):
    text = text.strip()
    if not re.fullmatch(rf"(?:{TIME}|\d+(?:\.\d{{1,3}})?)", text):
        raise ValueError("Enter seconds or a time such as 1:40.500.")
    seconds = Decimal(0)
    for part in text.split(":"):
        seconds = seconds * 60 + Decimal(part)
    result = to_ms(seconds)
    if result > MAX_MS:
        raise ValueError("Times must be within 24 hours.")
    return result


def time_text(ms):
    seconds, milli = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    time = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    return f"{time}.{milli:03d}".rstrip("0") if milli else time


@dataclass(frozen=True)
class Event:
    start_ms: int
    kind: str
    speed_percent: float | None = None
    duration_ms: int = 0

    @property
    def end_ms(self):
        return self.start_ms + self.duration_ms


@dataclass(frozen=True)
class Script:
    name: str
    duration_ms: int
    events: tuple[Event, ...] = ()
    source_note: str = ""
    description: str = ""
    director_approved: bool = False

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 120:
            raise ValueError("Enter a script name of 1 to 120 characters.")
        if type(self.duration_ms) is not int or not 0 < self.duration_ms <= MAX_MS:
            raise ValueError("Script duration must be greater than zero and at most 24 hours.")
        if not isinstance(self.source_note, str):
            raise ValueError("Invalid source note.")
        if not isinstance(self.description, str) or len(self.description) > 600:
            raise ValueError("Keep the script description to 600 characters.")
        if type(self.director_approved) is not bool:
            raise ValueError("Invalid Gwendolyn approval setting.")
        if len(self.events) > 10000:
            raise ValueError("The editor supports up to 10,000 events.")
        previous_speed = -1
        valve_ends = {"minus": -1, "plus": -1}
        for event in self.events:
            if (event.kind not in KINDS or type(event.start_ms) is not int
                    or type(event.duration_ms) is not int or not 0 <= event.start_ms < self.duration_ms
                    or event.end_ms > self.duration_ms):
                raise ValueError("Every event must fit inside the script duration.")
        ordered = tuple(sorted(self.events, key=lambda event: (event.start_ms, KINDS.index(event.kind))))
        for event in ordered:
            if event.kind == "speed":
                speed = event.speed_percent
                if (type(speed) not in (float, int) or not math.isfinite(speed)
                        or not 0 <= speed <= 100 or event.duration_ms != 0):
                    raise ValueError("Speed steps must be between 0% and 100%.")
                if event.start_ms == previous_speed:
                    raise ValueError("Only one speed step can start at a given time.")
                previous_speed = event.start_ms
            else:
                if event.speed_percent is not None or event.duration_ms <= 0:
                    raise ValueError("Valve blocks require a positive duration.")
                if event.start_ms < valve_ends[event.kind]:
                    raise ValueError(f"{LABELS[event.kind]} blocks cannot overlap each other.")
                valve_ends[event.kind] = event.end_ms
        object.__setattr__(self, "events", ordered)

    def speed_stats(self):
        steps = [event for event in self.events if event.kind == "speed"]
        ends = [event.start_ms for event in steps[1:]] + [self.duration_ms]
        area = sum(event.speed_percent * (end - event.start_ms) for event, end in zip(steps, ends))
        return round(area / self.duration_ms, 1), max((event.speed_percent for event in steps), default=0)

    def save(self, path):
        path = Path(path)
        content = json.dumps({"version": 1, **asdict(self)}, indent=2, ensure_ascii=False, allow_nan=False)
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content + "\n")
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path):
        with Path(path).open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("This is not a supported VacuGlide script file.")
        try:
            return cls(data["name"], data["duration_ms"],
                       tuple(Event(**event) for event in data["events"]), data.get("source_note", ""),
                       data.get("description", ""), data.get("director_approved", False))
        except (KeyError, TypeError) as exc:
            raise ValueError("The script file has missing or invalid fields.") from exc


class Preview:
    def __init__(self, script):
        self.duration_ms = script.duration_ms
        self.tracks = {kind: [] for kind in KINDS}
        for event in script.events:
            self.tracks[event.kind].append(event)
        self.starts = {kind: [event.start_ms for event in events]
                       for kind, events in self.tracks.items()}

    def at(self, position_ms, ceiling=25.0, gain=1.0):
        if not 0 <= position_ms < self.duration_ms:
            return 0.0, False, False

        def latest(kind):
            index = bisect_right(self.starts[kind], position_ms) - 1
            return self.tracks[kind][index] if index >= 0 else None

        speed = latest("speed")
        minus = latest("minus")
        plus = latest("plus")
        applied = min(ceiling, speed.speed_percent * gain) if speed is not None else 0.0
        return applied, bool(minus and position_ms < minus.end_ms), bool(plus and position_ms < plus.end_ms)


def _interval_ms(text):
    text = text.lower().strip()
    if text == "instant":
        return 0
    if text.startswith("<"):
        return None
    if ":" in text:
        return parse_time(text)
    numbers = {unit: Decimal(value) for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text)}
    return to_ms(sum(numbers.get(unit, 0) * factor for unit, factor in (("h", 3600), ("m", 60), ("s", 1))))


def _resolve_timestamps(displayed, exact, intervals, lower_delta, upper_delta):
    # Group rows joined by known durations. Every label constrains the group's origin.
    groups = []
    group = []
    offset = 0
    for index, (shown, precise, interval) in enumerate(zip(displayed, exact, intervals)):
        group.append((shown, precise, offset))
        if interval is None or index == len(displayed) - 1:
            lower = max(0, max(shown - offset + (0 if precise else lower_delta)
                               for shown, precise, offset in group))
            upper = min(shown - offset + (0 if precise else upper_delta)
                        for shown, precise, offset in group)
            preferred = round(median(shown - offset for shown, _, offset in group))
            groups.append((group, lower, upper, preferred, offset))
            group = []
            offset = 0
        else:
            offset += interval

    # Propagate the reachable origins. Neighbors are separated by one unknown interval.
    reachable = []
    for index, (_, lower, upper, preferred, _) in enumerate(groups):
        if index == 0 and displayed[0] == 0:
            upper = min(upper, 0)
        elif index:
            previous_offset = groups[index - 1][4]
            previous_low, previous_high, previous_preferred = reachable[-1]
            lower = max(lower, previous_low + previous_offset + 1)
            upper = min(upper, previous_high + previous_offset + 999)
            # Use a short draft gap where the clock labels offer no better estimate.
            preferred = max(preferred, previous_preferred + previous_offset + 100)
        if lower > upper:
            return None
        reachable.append((lower, upper, min(upper, max(lower, preferred))))

    # Preserve the anchors and work backward to resolve all the ambiguous gaps together.
    timestamps = []
    following_start = None
    for (group, _, _, _, offset), (lower, upper, preferred) in reversed(list(zip(groups, reachable))):
        if following_start is not None:
            lower = max(lower, following_start - offset - 999)
            upper = min(upper, following_start - offset - 1)
        origin = min(upper, max(lower, preferred))
        timestamps.extend(origin + entry[2] for entry in reversed(group))
        following_start = origin
    return list(reversed(timestamps))


def import_instructions(text, name, *, scale_to_25=True):
    text = unescape(text).translate(str.maketrans({"＜": "<", "\u200b": "", "\u2060": ""}))
    matches = list(ROW.finditer(text))
    matched_starts = {row.start("action") for row in matches}
    for index, action in enumerate(ACTION_LINE.finditer(text), 1):
        if action.start("action") not in matched_starts:
            number = action["ordinal"] or index
            label = " ".join(action["action"].split())
            raise ValueError(
                f"Check row {number} ({label}). Expected a time such as 5:57 and a duration "
                "such as 2s, 1:00, <1s, or Instant."
            )
    if not matches:
        raise ValueError("Paste Script instructions with action, at time, and duration for each row.")

    displayed = [parse_time(row["time"]) for row in matches]
    exact = ["." in row["time"] for row in matches]
    intervals = [_interval_ms(row["interval"]) for row in matches]
    if displayed != sorted(displayed):
        raise ValueError("The pasted action times are out of order.")

    # The site usually rounds whole-second labels. Also support truncated and mixed labels.
    for lower_delta, upper_delta in ((-500, 499), (0, 999), (-999, 999)):
        timestamps = _resolve_timestamps(displayed, exact, intervals, lower_delta, upper_delta)
        if timestamps is not None:
            break
    else:
        raise ValueError("The displayed times and durations conflict. Check that all instruction rows were copied.")
    final_interval = intervals[-1] if intervals[-1] is not None else 100
    current = timestamps[-1] + final_interval

    starts = {}
    events = []
    speeds = {}
    for at, row in zip(timestamps, matches):
        words = row["action"].lower().replace("−", "-").split()
        if words[0] == "speed":
            source_speed = float(re.search(r"[\d.]+", row["action"])[0])
            if not 0 <= source_speed <= 100:
                raise ValueError("Source speed must be between 0% and 100%.")
            speed = source_speed * 0.25 if scale_to_25 else source_speed
            speeds[at] = Event(at, "speed", speed)
            continue
        kind = "minus" if words[1] in ("minus", "-") else "plus"
        if words[2] == "open":
            if kind in starts:
                raise ValueError(f"{LABELS[kind]} opens twice without closing.")
            starts[kind] = at
        else:
            start = starts.pop(kind, None)
            if start is None:
                raise ValueError(f"{LABELS[kind]} closes before it opens.")
            events.append(Event(start, kind, duration_ms=at - start))
    if starts:
        raise ValueError("The pasted instructions leave a valve open. Include its Close row.")
    events.extend(speeds.values())
    duration = max(current, max((event.start_ms + 1 for event in events), default=1))
    note = "Imported from pasted Script instructions."
    unknown = intervals.count(None)
    if unknown == 1:
        note += " A <1 s interval was estimated from the displayed times."
    elif unknown > 1:
        note += f" {unknown} subsecond intervals were estimated from the displayed times."
    if scale_to_25:
        note += " Speed was scaled to 25% of the source values."
    return Script(name, duration, tuple(events), note)
