# backend/utils/team_config.py
# Shared parsing for Baker team configuration.

import os
from typing import Dict

DEFAULT_TEAM_MAP = {
    "KC": "NFL:KC_CHIEFS",
    "DAL": "NFL:DAL_COWBOYS",
}


def load_team_config() -> Dict[str, str]:
    """
    Parse BAKER_TEAM_MAP env of form "KC:NFL:KC_CHIEFS,DAL:NFL:DAL_COWBOYS".
    Falls back to DEFAULT_TEAM_MAP if not set or invalid.
    """
    raw = os.getenv("BAKER_TEAM_MAP")
    if not raw:
        return DEFAULT_TEAM_MAP

    parsed: Dict[str, str] = {}
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for part in parts:
        if ":" not in part:
            continue
        try:
            key, target = part.split(":", 1)
            key = key.strip().upper()
            target = target.strip()
            if key and target:
                parsed[key] = target
        except ValueError:
            continue

    return parsed or DEFAULT_TEAM_MAP
