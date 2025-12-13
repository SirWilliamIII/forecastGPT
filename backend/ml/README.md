# ML Validation Framework

This directory contains tools for backtesting and validating forecast models.

## Quick Start

### Apply Database Migration

```bash
# From repository root
psql $DATABASE_URL < db/migrations/003_forecast_metrics.sql
```

This creates the `forecast_metrics` table for storing backtest results.

### Run Full Backtest

```bash
cd backend

# All symbols, all horizons, 60 days
uv run python -m ml.evaluate_model_performance --output-csv --insert-db

# Specific configuration
uv run python -m ml.evaluate_model_performance \
    --symbols BTC-USD,ETH-USD \
    --horizons 1440,10080 \
    --days 30 \
    --output-csv
```

### Test on Small Dataset

```bash
# BTC only, 1-day horizon, 30 days, weekly sampling
uv run python -m ml.evaluate_model_performance \
    --symbols BTC-USD \
    --horizons 1440 \
    --days 30 \
    --sample-freq 7
```

## CLI Options

```
--symbols           Comma-separated symbols (default: all configured)
--horizons          Comma-separated horizons in minutes (default: 1440,10080,43200)
--days              Number of days to backtest (default: 60)
--lookback-days     Historical lookback for forecasts (default: 60)
--sample-freq       Sample every N days (default: 1 = daily)
--model-name        Model identifier (default: naive)
--output-csv        Save CSV reports to backend/notebooks/outputs/
--insert-db         Insert results to forecast_metrics table
```

## Output Files

When using `--output-csv`:

1. **Full Dataset**: `backend/notebooks/outputs/backtest_full_YYYYMMDD_HHMMSS.csv`
   - Every forecast with realized return
   - Columns: symbol, as_of, horizon_minutes, expected_return, realized_return,
     predicted_direction, actual_direction, direction_correct, confidence,
     sample_size, regime, model_name, schema_version

2. **Summary Statistics**: `backend/notebooks/outputs/backtest_summary_YYYYMMDD_HHMMSS.csv`
   - Aggregated metrics by symbol and horizon
   - Columns: symbol, horizon_minutes, total_forecasts, directional_accuracy,
     up_accuracy, down_accuracy, flat_accuracy, avg_confidence

## Modules

### backtest.py

Core backtesting engine. Generates historical forecasts and compares to realized returns.

**Key Functions:**

```python
from ml.backtest import build_backtest_dataset, save_backtest_to_db

# Build dataset
df = build_backtest_dataset(
    symbols=['BTC-USD', 'ETH-USD'],
    horizon_minutes=1440,
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
    lookback_days=60
)

# Save to database
rows_inserted = save_backtest_to_db(df)
```

**Features:**
- No lookahead bias (strict `< as_of` filtering)
- Temporal integrity guaranteed
- Regime classification at forecast time
- Batch operations for performance

### evaluate_model_performance.py

Comprehensive evaluation and reporting framework.

**Analyses:**
- Overall directional accuracy
- Confidence calibration (bucketed analysis)
- Performance by market regime
- Performance by horizon
- Performance by symbol
- Performance by confidence tier

**Output:**
- Console report with key findings
- CSV exports for further analysis
- Database insertion for tracking

## Validation Guarantees

### No Lookahead Bias

All forecasts use only data available at `as_of` timestamp:
- Events: `timestamp < as_of`
- Returns: `as_of < forecast_as_of`
- Features: Strictly historical
- Regime: Classified at exact `as_of` time

### Temporal Integrity

Enforced through:
- Timezone-aware UTC datetimes (raises ValueError if naive)
- Strict inequality (`<` not `<=`) in all temporal filters
- Historical `as_of` dates from `asset_returns` table
- No future data accessible during forecast generation

## Interpreting Results

### Overall Performance

```
Total forecasts: 440
Directional accuracy: 61.1%
```

**Good:** >55% accuracy (statistically significant with n>100)
**Excellent:** >65% accuracy
**Random:** ~50% accuracy

### Confidence Calibration

```
Confidence Bucket    Forecasts    Accuracy    Calibrated?
[0.6-0.8]           60           81.7%       ✗ Underconfident
```

**Well-calibrated:** accuracy ≈ bucket midpoint ± 10%
**Overconfident:** accuracy < bucket midpoint - 10%
**Underconfident:** accuracy > bucket midpoint + 10%

### Horizon Analysis

```
Horizon       Forecasts    Accuracy
1 day         209          47.9%  ❌
7 days        150          60.0%  ✅
30 days       81           97.5%  ⭐
```

Look for:
- Degradation with longer horizons (expected)
- Consistent performance across horizons (good signal)
- Dramatic improvements (noise reduction at longer scales)

### Regime Analysis

```
Regime        Forecasts    Accuracy
Uptrend       114          58.8%
Downtrend     172          62.2%
Chop          154          61.7%
```

Look for:
- All regimes >50% (model isn't memorizing one condition)
- Large variance (model needs regime-specific tuning)
- Specific weak regimes (focus improvement efforts)

## Common Issues

### Empty DataFrame

**Problem:** `No backtest data generated - DataFrame is empty`

**Solutions:**
- Check if `asset_returns` table has data for selected symbols/horizons
- Verify date range has available data
- Check database connection

### Low Accuracy

**Problem:** Directional accuracy <50%

**Possible causes:**
- Lookahead bias in forecast logic (check timestamp filtering)
- Incorrect feature calculation
- Regime classifier misalignment
- Model not suited for asset class (e.g., equities vs crypto)

### Connection Pool Warnings

**Problem:** `couldn't stop thread 'pool-1-worker-0' within 5.0 seconds`

**Impact:** Harmless - threads clean up on exit
**Fix:** Add explicit connection pool close (future enhancement)

## Integration with Other Systems

### With Event-Conditioned Forecaster

```python
from models.event_return_forecaster import forecast_event_return

# Modify backtest.py to use event forecaster
# (Currently only tests naive forecaster)
```

### With ML Models

```python
from models.trained.asset_return_rf import predict

# Add model_name parameter
# Load model predictions instead of naive forecasts
```

### With Real-Time Monitoring

Query `forecast_metrics` table:

```sql
-- Recent forecast performance
SELECT
    symbol,
    horizon_minutes,
    AVG(CASE WHEN direction_correct THEN 1.0 ELSE 0.0 END) as accuracy,
    AVG(confidence) as avg_confidence,
    COUNT(*) as forecasts
FROM forecast_metrics
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY symbol, horizon_minutes;
```

## Best Practices

1. **Always test on small dataset first** (30 days, 1 symbol)
2. **Use --sample-freq for quick iterations** (weekly sampling = 7x faster)
3. **Save CSV for analysis** (Excel, Python notebooks, etc.)
4. **Insert to DB for tracking** (monitor model degradation over time)
5. **Check statistical significance** (n>30 per bucket minimum)
6. **Validate assumptions** (e.g., horizon normalization correctness)

## Future Enhancements

- [ ] Event-conditioned forecast backtesting
- [ ] ML model comparison framework
- [ ] Automated A/B testing (naive vs event vs ML)
- [ ] Time-series plots (accuracy over time)
- [ ] Sharpe ratio calculation (risk-adjusted returns)
- [ ] Drawdown analysis (maximum loss sequences)
- [ ] Cross-validation splits (train/test by date)
- [ ] Hyperparameter optimization integration

## References

- PLAN_MAESTRO.md - Section 10-12 (validation framework design)
- BACKTEST_RESULTS.md - Comprehensive analysis of initial backtest results
- confidence_utils.py - Horizon-normalized confidence calculation
- naive_asset_forecaster.py - Baseline model being validated

---

Last updated: December 12, 2025
Framework version: v1.0
