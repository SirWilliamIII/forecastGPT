# backend/cli/forecast_cli.py

import argparse
from datetime import datetime, timezone
from uuid import UUID

from models.naive_asset_forecaster import (
    forecast_asset as naive_forecast_asset,
)
from models.event_return_forecaster import forecast_event_return


def cmd_asset(args: argparse.Namespace) -> None:
    """Run naive numeric forecast for an asset."""
    as_of = datetime.now(tz=timezone.utc)

    result = naive_forecast_asset(
        symbol=args.symbol,
        as_of=as_of,
        horizon_minutes=args.horizon,
        lookback_days=args.lookback_days,
    )

    d = result.to_dict()

    print("\n=== Asset Forecast ===")
    print(f"Symbol          : {d['symbol']}")
    print(f"As of (UTC)     : {d['as_of']}")
    print(f"Horizon (min)   : {d['horizon_minutes']}")
    print(f"Direction       : {d.get('direction', 'n/a')}")
    print(f"Confidence      : {d.get('confidence', 'n/a')}")
    print(f"Expected return : {d['mean_return']:.6f}")
    print(f"Vol (return)    : {d['vol_return']:.6f}")
    print(f"Lookback (days) : {d['lookback_days']}")
    print(f"N points        : {d['n_points']}")

    features = d.get("features") or {}
    if features:
        print("\n--- Key Features ---")
        # print a few interesting ones if present
        for k in sorted(features.keys()):
            print(f"{k:28s}: {features[k]}")


def cmd_event(args: argparse.Namespace) -> None:
    """Run event-conditioned forecast for an asset."""
    event_id = UUID(args.event_id)

    result = forecast_event_return(
        event_id=event_id,
        symbol=args.symbol,
        horizon_minutes=args.horizon,
        k_neighbors=args.k_neighbors,
        lookback_days=args.lookback_days,
        price_window_minutes=args.price_window_minutes,
        alpha=args.alpha,
    )

    print("\n=== Event-Conditioned Forecast ===")
    print(f"Event ID        : {result.event_id}")
    print(f"Symbol          : {result.symbol}")
    print(f"Horizon (min)   : {result.horizon_minutes}")
    print(f"Expected return : {result.expected_return:.6f}")
    print(f"Std return      : {result.std_return:.6f}")
    print(f"P(up)           : {result.p_up:.3f}")
    print(f"P(down)         : {result.p_down:.3f}")
    print(f"Samples used    : {result.sample_size}")
    print(f"Neighbors used  : {result.neighbors_used}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bloomberg-gpt-cli",
        description="CLI for BloombergGPT-style forecaster (asset + event-conditioned)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # -------------------
    # asset forecast cmd
    # -------------------
    p_asset = subparsers.add_parser(
        "asset",
        help="Run naive numeric forecast for an asset (BTC-USD, ETH-USD, etc.)",
    )
    p_asset.add_argument(
        "--symbol",
        required=True,
        help="Asset symbol, e.g. BTC-USD",
    )
    p_asset.add_argument(
        "--horizon",
        type=int,
        default=1440,
        help="Prediction horizon in minutes (default: 1440 = 1d)",
    )
    p_asset.add_argument(
        "--lookback-days",
        type=int,
        default=60,
        help="Lookback window in days for historical returns (default: 60)",
    )
    p_asset.set_defaults(func=cmd_asset)

    # --------------------
    # event forecast cmd
    # --------------------
    p_event = subparsers.add_parser(
        "event",
        help="Run event-conditioned forecast for an asset based on an event_id",
    )
    p_event.add_argument(
        "--event-id",
        required=True,
        help="UUID of the event row in the events table",
    )
    p_event.add_argument(
        "--symbol",
        required=True,
        help="Asset symbol, e.g. BTC-USD",
    )
    p_event.add_argument(
        "--horizon",
        type=int,
        default=1440,
        help="Prediction horizon in minutes (default: 1440 = 1d)",
    )
    p_event.add_argument(
        "--k-neighbors",
        type=int,
        default=25,
        help="Number of semantic neighbors to use (default: 25)",
    )
    p_event.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Lookback window in days for searching neighbors/returns (default: 365)",
    )
    p_event.add_argument(
        "--price-window-minutes",
        type=int,
        default=60,
        help="Window around the event timestamp for price context (default: 60)",
    )
    p_event.add_argument(
        "--alpha",
        type=float,
        default=0.5,
        help="Exponential distance decay parameter (default: 0.5)",
    )
    p_event.set_defaults(func=cmd_event)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
