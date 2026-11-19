from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from .response_defaults import RESPONSE_DEFAULTS


def settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "Vector1A" / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return deepcopy(RESPONSE_DEFAULTS)
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(values: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
