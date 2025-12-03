# backend/ingest/baker_projections.py
# Ingest Baker NFL projected win probabilities for selected teams.

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import requests
from requests import Response

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from numeric.asset_projections import upsert_projection
from utils.team_config import load_team_config
from db import get_conn

BAKER_API_KEY = os.getenv("BAKER_API_KEY") or os.getenv("SPORTS_DATA_API_KEY")
BASE_URL = os.getenv("BAKER_BASE_URL", "https://baker-api.sportsdata.io/baker/v2/nfl")
CHANGELOG_URL = f"{BASE_URL}/changelog"
GAME_URL = f"{BASE_URL}/projections/games/{{game_id}}"
ADV_QUERY_URL = f"{BASE_URL}/query/games/{{game_id}}"

# target teams to ingest: abbreviation -> target_id
TEAM_CONFIG: Dict[str, str] = load_team_config()
TEAM_KEYS: Set[str] = set(TEAM_CONFIG.keys())

TIMEOUT_SECONDS = float(os.getenv("BAKER_TIMEOUT_SECONDS", "10.0"))
MAX_GAMES = int(os.getenv("BAKER_MAX_GAMES", "200"))
HORIZON_MINUTES = int(os.getenv("BAKER_HORIZON_MINUTES", str(7 * 24 * 60)))  # default 1 week
MODEL_SOURCE = "baker_v2"
METRIC = "win_prob"
# Advanced query currently returns 422 with unknown schema issues; default off to avoid noise.
ENABLE_ADV_QUERY = os.getenv("BAKER_ENABLE_ADV_QUERY", "false").lower() in ("true", "1", "yes")
ENABLE_ADV_QUERY = os.getenv("BAKER_ENABLE_ADV_QUERY", "true").lower() in ("true", "1", "yes")


def _fetch_json(
    url: str, params: Optional[Dict[str, str]] = None, body: Optional[dict] = None, method: str = "GET"
) -> dict | list:
    if BAKER_API_KEY is None:
        raise RuntimeError("BAKER_API_KEY or SPORTS_DATA_API_KEY must be set for Baker ingestion.")

    if params is None:
        params = {}
    # Prefer header auth to avoid leaking the key in URLs. Query key is omitted by default.
    headers = {"Ocp-Apim-Subscription-Key": BAKER_API_KEY}

    if method.upper() == "POST":
        resp: Response = requests.post(url, params=params, headers=headers, json=body or {}, timeout=TIMEOUT_SECONDS)
    else:
        resp: Response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    content_type = resp.headers.get("content-type", "")
    if "json" not in content_type:
        raise RuntimeError(f"Non-JSON response from {url} (content-type={content_type})")
    resp.raise_for_status()
    return resp.json()


def _parse_datetime_utc(dt_str: str | None) -> Optional[datetime]:
    if not dt_str:
        return None
    # Baker returns "YYYY-MM-DD HH:MM:SS"
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        dt = datetime.strptime(dt_str, fmt)
    except Exception:
        try:
            dt = datetime.fromisoformat(dt_str)
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def discover_game_runs(max_games: int) -> List[Tuple[int, Optional[str]]]:
    """
    Read changelog and return recent game IDs (with run_id) that include our teams.
    Deduplicates by game_id, preserving the first seen (assumed latest).
    """
    data = _fetch_json(CHANGELOG_URL)
    if not isinstance(data, list):
        print(f"[baker] Unexpected changelog payload type: {type(data)}")
        return []

    selected: List[Tuple[int, Optional[str]]] = []
    seen: Set[int] = set()

    for entry in data:
        teams = set(entry.get("teams") or [])
        if not teams.intersection(TEAM_KEYS):
            continue

        run_id = entry.get("id")
        games = entry.get("games") or []
        for gid in games:
            if not isinstance(gid, int):
                continue
            if gid in seen:
                continue
            selected.append((gid, run_id))
            seen.add(gid)
            if len(selected) >= max_games:
                return selected

    return selected


def _extract_projections(game: dict, run_id: Optional[str]) -> List[Tuple[str, datetime, float, int, Optional[str], Optional[str], Dict[str, float]]]:
    """
    Returns a list of (symbol, as_of, win_prob, game_id, opponent, opponent_name, meta) rows for configured teams.
    """
    results: List[Tuple[str, datetime, float, int, Optional[str], Optional[str], Dict[str, float]]] = []

    game_id = game.get("sportsdata_id")
    as_of = _parse_datetime_utc(game.get("date"))
    if as_of is None or not game_id:
        return results

    home_abbr = game.get("home_team")
    away_abbr = game.get("away_team")
    home_proj = game.get("home_team_projections") or {}
    away_proj = game.get("away_team_projections") or {}
    home_name = home_proj.get("name")
    away_name = away_proj.get("name")

    if home_abbr in TEAM_CONFIG:
        win = home_proj.get("win")
        if isinstance(win, (int, float)):
            meta = {
                "spread": float(game.get("point_spread", 0.0) or 0.0),
                "over_under": float(game.get("over_under", 0.0) or 0.0),
                "home_team": 1.0,
            }
            results.append((TEAM_CONFIG[home_abbr], as_of, float(win), game_id, away_abbr, away_name, meta))

    if away_abbr in TEAM_CONFIG:
        win = away_proj.get("win")
        if isinstance(win, (int, float)):
            meta = {
                "spread": float(game.get("point_spread", 0.0) or 0.0),
                "over_under": float(game.get("over_under", 0.0) or 0.0),
                "home_team": 0.0,
            }
            results.append((TEAM_CONFIG[away_abbr], as_of, float(win), game_id, home_abbr, home_name, meta))

    return results


def _adv_query_game(game_id: int) -> Optional[dict]:
    """
    Use the advanced query endpoint to fetch projections (includes win_pct and odds).
    """
    body = {
        "select": [
            {"category": "game", "metric": "win_pct", "measure": "average", "period": "final"},
            {"category": "game", "metric": "point_spread", "measure": "average", "period": "final"},
            {"category": "game", "metric": "over_under", "measure": "average", "period": "final"},
            {"category": "game", "metric": "home_team_win_pct", "measure": "average", "period": "final"},
            {"category": "game", "metric": "away_team_win_pct", "measure": "average", "period": "final"},
            {"category": "game", "metric": "home_team_money_line", "measure": "average", "period": "final"},
            {"category": "game", "metric": "away_team_money_line", "measure": "average", "period": "final"},
        ],
        "where": [
            {
                "category": "game",
                "metric": "win_pct",
                "period": "final",
                "operator": "ge",
                "value": 0,
            }
        ],
    }
    try:
        resp = _fetch_json(ADV_QUERY_URL.format(game_id=game_id), body=body, method="POST")
        if isinstance(resp, dict):
            return resp
    except Exception as e:
        print(f"[baker] adv query failed for game_id={game_id}: {e}")
    return None


def _merge_adv_into_game(game: dict, adv: dict) -> dict:
    """
    Merge advanced query metrics into the game dict for consistent extraction.
    """
    if not adv:
        return game
    # Extract metrics keyed by metric name
    metrics = {}
    for item in adv.get("data", []):
        metric = item.get("metric")
        value = item.get("value")
        metrics[metric] = value
    game = dict(game)
    # Map back to fields we expect
    if "point_spread" in metrics:
        game["point_spread"] = metrics["point_spread"]
    if "over_under" in metrics:
        game["over_under"] = metrics["over_under"]
    # Win pct metrics can complement team projections
    if "home_team_win_pct" in metrics:
        home_proj = game.get("home_team_projections") or {}
        home_proj = dict(home_proj)
        home_proj["win"] = metrics["home_team_win_pct"]
        game["home_team_projections"] = home_proj
    if "away_team_win_pct" in metrics:
        away_proj = game.get("away_team_projections") or {}
        away_proj = dict(away_proj)
        away_proj["win"] = metrics["away_team_win_pct"]
        game["away_team_projections"] = away_proj
    # Money lines into meta
    if "home_team_money_line" in metrics:
        game["home_team_money_line"] = metrics["home_team_money_line"]
    if "away_team_money_line" in metrics:
        game["away_team_money_line"] = metrics["away_team_money_line"]
    return game


def ingest_once(max_games: int = MAX_GAMES) -> Tuple[int, int]:
    """
    Ingest recent projections for configured teams.

    Returns (inserted, skipped).
    """
    game_runs = discover_game_runs(max_games)
    print(f"[baker] Found {len(game_runs)} candidate games from changelog")

    inserted = 0
    skipped = 0
    had_error = False
    last_error_message = None

    for game_id, run_id in game_runs:
        try:
            game = _fetch_json(GAME_URL.format(game_id=game_id))
            if ENABLE_ADV_QUERY:
                adv = _adv_query_game(game_id)
                if adv:
                    game = _merge_adv_into_game(game, adv)
        except Exception as e:
            print(f"[baker] ✗ game_id={game_id}: fetch error: {e}")
            skipped += 1
            had_error = True
            last_error_message = str(e)
            continue

        rows = _extract_projections(game, run_id)
        if not rows:
            skipped += 1
            continue

        for symbol, as_of, win_prob, gid, opponent, opponent_name, meta in rows:
            try:
                upsert_projection(
                    symbol=symbol,
                    as_of=as_of,
                    horizon_minutes=HORIZON_MINUTES,
                    metric=METRIC,
                    projected_value=win_prob,
                    model_source=MODEL_SOURCE,
                    game_id=gid,
                    run_id=run_id,
                    opponent=opponent,
                    opponent_name=opponent_name,
                    meta=meta,
                )
                inserted += 1
            except Exception as e:
                print(f"[baker] ✗ insert failed for game_id={gid}, symbol={symbol}: {e}")
                skipped += 1
                had_error = True
                last_error_message = str(e)

    print(f"[baker] Done. Inserted {inserted}, skipped {skipped}")
    # update ingest status
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingest_status (job_name, last_success, last_rows_inserted, updated_at)
                    VALUES (%s, now(), %s, now())
                    ON CONFLICT (job_name)
                    DO UPDATE SET
                        last_success = EXCLUDED.last_success,
                        last_rows_inserted = EXCLUDED.last_rows_inserted,
                        updated_at = now(),
                        last_error = NULL,
                        last_error_message = NULL
                    """,
                    ("baker_projections", inserted),
                )
                if had_error:
                    cur.execute(
                        """
                        UPDATE ingest_status
                        SET last_error = now(),
                            last_error_message = %s,
                            updated_at = now()
                        WHERE job_name = %s
                        """,
                        (last_error_message, "baker_projections"),
                    )
    except Exception as e:
        print(f"[baker] ⚠️ failed to update ingest_status: {e}")
    return inserted, skipped


def main() -> None:
    ingest_once()


if __name__ == "__main__":
    main()
