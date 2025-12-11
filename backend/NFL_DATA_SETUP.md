# NFL Data Setup Guide

Quick reference for setting up and maintaining NFL game data.

## Initial Data Load (One-time Setup)

The NFL forecasting system requires historical game data. You have two options:

### Option 1: GitHub CSV Datasets (Recommended - Free, Historical Data)

**Coverage:** 2012-2024, ~1,600+ games with weather data

**Step 1:** Download CSV files
```bash
# Nolanole dataset (2012-2018 with detailed weather)
curl -L -o /tmp/nfl_weather_games.csv \
  "https://github.com/Nolanole/NFL-Weather-Project/raw/master/data/all_games_weather.csv"

# nflverse dataset (2019-2024 with temp/wind/roof/surface)
curl -L -o /tmp/nflverse_games.csv \
  "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
```

**Step 2:** Run backfill
```bash
cd backend
uv run python -m ingest.backfill_github_nfl
```

**Result:** ~1,600 games loaded across all 8 configured teams

### Option 2: SportsData.io API (Current Season Only)

**Coverage:** 2024 season only (free tier limitation)

**Requirement:** `SPORTSDATA_API_KEY` in `backend/.env`

```bash
cd backend
uv run python -m ingest.backfill_sportsdata_nfl --seasons 2024
```

**Result:** ~100-200 games for current season

## Daily Updates (Automatic)

Once you have initial data, the system **automatically updates** during NFL season:

- **When:** Daily (configurable, default: 24 hours)
- **What:** Fetches last 4 weeks of games (catches delayed scores)
- **Season-aware:** Only runs Sept-Feb, skips Mar-Aug
- **Source:** SportsData.io API

**Configuration** (`backend/.env`):
```bash
NFL_OUTCOMES_INTERVAL_HOURS=24      # Run daily
NFL_OUTCOMES_LOOKBACK_WEEKS=4       # Fetch last 4 weeks
DISABLE_NFL_OUTCOMES_INGEST=false   # Enable (default)
```

**Manual trigger:**
```bash
cd backend
uv run python -c "from app import run_nfl_outcomes_daily; run_nfl_outcomes_daily()"
```

## Available Teams

The system currently tracks **8 NFL teams**:

| Team | Symbol | Games (2012-2024) |
|------|--------|-------------------|
| San Francisco 49ers | `NFL:SF_49ERS` | 217 |
| Kansas City Chiefs | `NFL:KC_CHIEFS` | 214 |
| New York Giants | `NFL:NYG_GIANTS` | 214 |
| Philadelphia Eagles | `NFL:PHI_EAGLES` | 213 |
| Dallas Cowboys | `NFL:DAL_COWBOYS` | 212 |
| Washington Commanders | `NFL:WSH_COMMANDERS` | 211 |
| Buffalo Bills | `NFL:BUF_BILLS` | 206 |
| Detroit Lions | `NFL:DET_LIONS` | 212 |

**Adding more teams:**
Edit `backend/utils/team_config.py` and `backend/config.py`

## ML Model

**Current Model:** v2.0
- **Training Data:** 850 games (4 NFC East teams)
- **Test Accuracy:** 58.8% (realistic, not overfitted)
- **Features:** 9 (win_pct, point_diff, streaks, etc.)
- **Algorithm:** Logistic Regression with L2 regularization

**Retraining:**
```bash
cd backend
uv run python -m notebooks.nfl_forecaster_training
```

**When to retrain:**
- After adding ~100+ new games
- At end of season
- When model accuracy degrades

## API Endpoints

### Team Data
```bash
# List all teams
curl http://localhost:9000/nfl/teams

# Team statistics
curl http://localhost:9000/nfl/teams/NFL:DAL_COWBOYS/stats

# Team game history (paginated, filterable)
curl "http://localhost:9000/nfl/teams/NFL:DAL_COWBOYS/games?season=2024&outcome=win"

# Recent games across all teams
curl "http://localhost:9000/nfl/games/recent?limit=10"
```

### ML Predictions
```bash
# ML model info
curl http://localhost:9000/forecast/nfl/ml/model/info

# Game forecast
curl "http://localhost:9000/forecast/nfl/ml/game?team_symbol=NFL:DAL_COWBOYS&game_date=2024-12-15T18:00:00Z"
```

## Frontend

**URL:** http://localhost:3000/nfl

**Features:**
- Team selector (8 teams)
- Team statistics card (record, streaks, point differential)
- Game history table (filterable by season/outcome)
- Win probability projections
- Event-based forecasts

## Data Storage

**Database Table:** `asset_returns`

**Schema:**
- `symbol` - Team symbol (e.g., "NFL:DAL_COWBOYS")
- `as_of` - Game date (timezone-aware UTC)
- `horizon_minutes` - Always 10080 (7 days)
- `price_start` - Always 100 (baseline)
- `price_end` - 100 + point_differential
- `realized_return` - +1 (win), -1 (loss)

**Unique Constraint:** `(symbol, as_of, horizon_minutes)`
- Prevents duplicate games
- Safe to re-run backfill scripts

## Troubleshooting

### No NFL Data on Dashboard
```bash
# Check if data exists
psql $DATABASE_URL -c "SELECT COUNT(*) FROM asset_returns WHERE symbol LIKE 'NFL:%';"

# If zero, run initial backfill (see Option 1 or 2 above)
```

### Daily Updates Not Running
```bash
# Check scheduler is enabled
grep DISABLE_NFL_OUTCOMES_INGEST backend/.env

# Should be: DISABLE_NFL_OUTCOMES_INGEST=false (or not set)

# Check season (only runs Sept-Feb)
uv run python -m utils.nfl_schedule
```

### Model Not Loading
```bash
# Check model files exist
ls -lh backend/models/trained/nfl_logreg_v2.0*

# Should see:
# - nfl_logreg_v2.0.pkl
# - nfl_logreg_v2.0_metadata.json
```

### API Errors
```bash
# Check backend logs
# Look for: [nfl_ml] Loaded model v2.0 with 9 features

# Test endpoints
curl http://localhost:9000/nfl/teams
curl http://localhost:9000/forecast/nfl/ml/model/info
```

## Quick Start Checklist

- [ ] Download CSV datasets (GitHub)
- [ ] Run `backfill_github_nfl.py`
- [ ] Verify data: `SELECT COUNT(*) FROM asset_returns WHERE symbol LIKE 'NFL:%';`
- [ ] Start server: `./run-dev.sh`
- [ ] Visit: http://localhost:3000/nfl
- [ ] (Optional) Add `SPORTSDATA_API_KEY` for daily updates

## Cost Efficiency

**Initial Load:**
- GitHub CSVs: **Free** (1,600+ games)
- SportsData API (2024 only): ~100 API calls

**Daily Updates:**
- During season: ~100 API calls/day (mostly duplicates)
- Off-season: 0 API calls (automatic skip)

**Annual Estimate:**
- ~18,000 API calls (180 season days × 100 calls)
- Well within free/low-tier limits
