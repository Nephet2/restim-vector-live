from __future__ import annotations

from dataclasses import dataclass
import base64
import html
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request


@dataclass(frozen=True)
class MediaSnapshot:
    player: str
    connected: bool
    state: str = "unknown"
    position_seconds: float | None = None
    duration_seconds: float | None = None
    rate: float = 1.0
    media_path: str | None = None
    title: str | None = None
    error: str | None = None
    raw_position: str | None = None
    raw_duration: str | None = None
    position_source: str | None = None


def _http_text(url: str, *, timeout: float = 0.35, auth: tuple[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Vector1A/1.6"})
    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def _file_uri_to_path(uri: str | None) -> str | None:
    if not uri:
        return None
    try:
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme.lower() != "file":
            return None
        path = urllib.parse.unquote(parsed.path or "")
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return os.path.normpath(path)
    except Exception:
        return None


def _vlc_current_uri(node: object, current_id: str | int | None) -> str | None:
    if isinstance(node, dict):
        if current_id is not None and str(node.get("id")) == str(current_id) and node.get("uri"):
            return str(node.get("uri"))
        if str(node.get("current", "")).lower() == "current" and node.get("uri"):
            return str(node.get("uri"))
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                found = _vlc_current_uri(child, current_id)
                if found:
                    return found
    elif isinstance(node, list):
        for item in node:
            found = _vlc_current_uri(item, current_id)
            if found:
                return found
    return None


def poll_vlc(host: str = "127.0.0.1", port: int = 8080, password: str = "") -> MediaSnapshot:
    base = f"http://{host}:{int(port)}"
    try:
        status = json.loads(_http_text(base + "/requests/status.json", auth=("", password)))
        state = str(status.get("state") or "unknown")
        pos = float(status["time"]) if status.get("time") is not None else None
        dur = float(status["length"]) if status.get("length") is not None else None
        rate = float(status.get("rate") or 1.0)
        title = None
        media_path = None
        info = status.get("information") if isinstance(status, dict) else None
        if isinstance(info, dict):
            category = info.get("category")
            if isinstance(category, dict):
                meta = category.get("meta")
                if isinstance(meta, dict):
                    title = str(meta.get("title") or meta.get("filename") or "") or None
                    raw_path = meta.get("path") or meta.get("filename")
                    if raw_path and os.path.isabs(str(raw_path)):
                        media_path = os.path.normpath(str(raw_path))
        try:
            playlist = json.loads(_http_text(base + "/requests/playlist.json", auth=("", password)))
            uri = _vlc_current_uri(playlist, status.get("currentplid"))
            media_path = _file_uri_to_path(uri) or media_path
        except Exception:
            pass
        if not title and media_path:
            title = os.path.basename(media_path)
        return MediaSnapshot("VLC", True, state, pos, dur, rate, media_path, title)
    except Exception as exc:
        return MediaSnapshot("VLC", False, error=str(exc))


def _parse_clock_value(text: str | None) -> float | None:
    if text is None:
        return None
    s = html.unescape(re.sub(r"<[^>]*>", "", str(text))).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split(":")
    if len(parts) in (2, 3):
        try:
            nums = [float(x) for x in parts]
            if len(nums) == 2:
                return nums[0] * 60.0 + nums[1]
            return nums[0] * 3600.0 + nums[1] * 60.0 + nums[2]
        except ValueError:
            return None
    return None


def _extract_mpc_value(source: str, key: str) -> str | None:
    patterns = [
        rf'<[^>]+(?:id|name)=["\']{re.escape(key)}["\'][^>]*>(.*?)</[^>]+>',
        rf'<!--\s*{re.escape(key)}\s*-->(.*?)<!--\s*/{re.escape(key)}\s*-->',
        rf'\b{re.escape(key)}\b\s*[:=]\s*["\']?([^\r\n<"\']+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return html.unescape(re.sub(r"<[^>]*>", "", m.group(1))).strip()
    return None


def _mpc_milliseconds(value: str | None) -> float | None:
    """Parse MPC's numeric position/duration variables, which are milliseconds."""
    if value is None:
        return None
    try:
        return float(str(value).strip()) / 1000.0
    except (TypeError, ValueError):
        return None


def _normalize_mpc_state(state_value: str | None, state_string: str | None) -> str:
    # MPC's variables page exposes a numeric state. In current MPC-HC/BE builds
    # 0=stopped/closed, 1=paused, 2=playing. Prefer it over statestring because
    # statestring is localized on non-English installations.
    try:
        code = int(str(state_value).strip()) if state_value is not None else None
    except (TypeError, ValueError):
        code = None
    if code == 2:
        return "playing"
    if code == 1:
        return "paused"
    if code == 0:
        return "stopped"
    text = str(state_string or state_value or "unknown").strip().lower()
    if text in {"play", "playing"}:
        return "playing"
    if text in {"pause", "paused"}:
        return "paused"
    if text in {"stop", "stopped", "closed"}:
        return "stopped"
    return text or "unknown"


def poll_mpc(host: str = "127.0.0.1", port: int = 13579) -> MediaSnapshot:
    base = f"http://{host}:{int(port)}"
    try:
        source = _http_text(base + "/variables.html")
        path = (_extract_mpc_value(source, "filepath") or
                _extract_mpc_value(source, "file") or
                _extract_mpc_value(source, "filename"))
        if path:
            path = urllib.parse.unquote(path.strip())
            if path.lower().startswith("file://"):
                path = _file_uri_to_path(path)
            elif not os.path.isabs(path):
                folder = _extract_mpc_value(source, "filedir")
                if folder:
                    path = os.path.join(folder, path)
            if path:
                path = os.path.normpath(path)

        raw_pos = _extract_mpc_value(source, "position")
        raw_dur = _extract_mpc_value(source, "duration")
        raw_pos_string = _extract_mpc_value(source, "positionstring")
        raw_dur_string = _extract_mpc_value(source, "durationstring")

        # Critical detail: MPC's numeric <position> and <duration> variables are
        # milliseconds, while positionstring/durationstring are whole-second clock
        # strings. Prefer numeric milliseconds for precision, with strings as fallback.
        pos = _mpc_milliseconds(raw_pos)
        position_source = "position_ms"
        if pos is None:
            pos = _parse_clock_value(raw_pos_string)
            position_source = "positionstring" if pos is not None else None
        dur = _mpc_milliseconds(raw_dur)
        if dur is None:
            dur = _parse_clock_value(raw_dur_string)

        state_value = _extract_mpc_value(source, "state")
        state_string = _extract_mpc_value(source, "statestring")
        state = _normalize_mpc_state(state_value, state_string)
        rate_text = _extract_mpc_value(source, "playbackrate")
        try:
            rate = float(rate_text) if rate_text else 1.0
        except ValueError:
            rate = 1.0
        title = os.path.basename(path) if path else (_extract_mpc_value(source, "filename") or None)
        return MediaSnapshot("MPC", True, state, pos, dur, rate, path, title,
                             raw_position=raw_pos, raw_duration=raw_dur,
                             position_source=position_source)
    except Exception as exc:
        return MediaSnapshot("MPC", False, error=str(exc))


def find_matching_funscript(media_path: str | None, library_dirs: list[str] | tuple[str, ...] = ()) -> str | None:
    if not media_path:
        return None
    media = Path(media_path)
    basename = media.stem
    exact_name = basename + ".funscript"
    candidates: list[Path] = []
    if media.parent:
        candidates.append(media.parent / exact_name)
    for folder in library_dirs:
        if not folder:
            continue
        root = Path(os.path.expanduser(folder))
        candidates.append(root / exact_name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    # Library fallback: exact basename anywhere below the configured roots.
    for folder in library_dirs:
        if not folder:
            continue
        root = Path(os.path.expanduser(folder))
        if not root.is_dir():
            continue
        try:
            for match in root.rglob(exact_name):
                if match.is_file():
                    return str(match.resolve())
        except OSError:
            continue
    return None
