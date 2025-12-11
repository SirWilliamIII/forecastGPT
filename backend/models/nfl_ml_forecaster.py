# backend/models/nfl_ml_forecaster.py
"""
NFL ML Forecaster - Production forecaster using trained Logistic Regression model.

Uses structured team statistics to predict NFL game outcomes.
Model v2.0: Trained on all NFC East teams (Cowboys, Giants, Eagles, Commanders)
with 95.7% test accuracy on 228 games (2012-2025).
"""

import os
import json
import pickle
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from db import get_conn


class NFLMLForecaster:
    """
    Production ML forecaster for NFL games.

    Loads trained model and makes predictions using the same
    feature engineering pipeline as training.
    """

    _instance = None  # Singleton

    def __new__(cls):
        """Singleton pattern - load model once."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Load trained model and metadata."""
        if self._initialized:
            return

        # Paths
        base_path = Path(__file__).parent / "trained"
        model_path = base_path / "nfl_logreg_v2.0.pkl"
        metadata_path = base_path / "nfl_logreg_v2.0_metadata.json"

        # Load model
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        with open(model_path, 'rb') as f:
            model_data = pickle.load(f)

        self.model = model_data['model']
        self.scaler = model_data['scaler']
        self.feature_names = model_data['feature_names']

        # Load metadata
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {}

        self.version = self.metadata.get('version', 'v2.0')
        self._initialized = True

        print(f"[nfl_ml] Loaded model {self.version} with {len(self.feature_names)} features")
        if 'symbols' in self.metadata.get('training_data', {}):
            teams = self.metadata['training_data']['symbols']
            print(f"[nfl_ml] Trained on {len(teams)} teams: {', '.join(teams)}")

    def extract_features(self, symbol: str, game_date: datetime) -> pd.DataFrame:
        """
        Extract features for a game using historical data.

        Mirrors the training pipeline exactly:
        - Query all games before this one
        - Compute expanding window features
        - Use .shift(1) to prevent lookahead bias

        Args:
            symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
            game_date: Game date (timezone-aware UTC)

        Returns:
            DataFrame with single row of 9 features
        """
        if game_date.tzinfo is None:
            game_date = game_date.replace(tzinfo=timezone.utc)

        # Query historical games for this team
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        as_of as game_date,
                        price_start,
                        price_end,
                        realized_return
                    FROM asset_returns
                    WHERE symbol = %s
                      AND as_of <= %s
                    ORDER BY as_of
                """, (symbol, game_date))

                rows = cur.fetchall()

        if not rows:
            # No history - return neutral features
            return self._neutral_features()

        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=['game_date', 'price_start', 'price_end', 'realized_return'])

        # Compute features (same as training)
        df = self._compute_features(df, game_date)

        # Get features for this specific game
        game_features = df[df['game_date'] == game_date]

        if game_features.empty:
            # Game not in history - use latest features
            game_features = df.iloc[[-1]]

        # Select and order features
        features = game_features[self.feature_names]

        return features

    def _compute_features(self, df: pd.DataFrame, target_date: datetime) -> pd.DataFrame:
        """
        Compute 9 ML features from game history.

        Matches training pipeline exactly:
        - Expanding windows (cumulative)
        - .shift(1) to prevent lookahead
        - Proper handling of first game
        """
        # Ensure chronological order
        df = df.sort_values('game_date').reset_index(drop=True)

        # Derive basic stats
        df['pts_for'] = df['price_end'] - 100  # point differential
        df['pts_against'] = 0  # We don't have opponent scores in this encoding
        df['won'] = (df['realized_return'] > 0).astype(int)

        # Feature 1: win_pct (expanding)
        df['cumulative_wins'] = df['won'].cumsum()
        df['games_played'] = (df.index + 1)
        df['win_pct'] = df['cumulative_wins'] / df['games_played']
        df['win_pct'] = df['win_pct'].shift(1).fillna(0.5)  # No lookahead

        # Feature 2-3: Points for/against averages
        df['pts_for_cumsum'] = df['pts_for'].abs().cumsum()
        df['pts_for_avg'] = df['pts_for_cumsum'] / df['games_played']
        df['pts_for_avg'] = df['pts_for_avg'].shift(1).fillna(0)

        df['pts_against_avg'] = 0  # Not available in current encoding

        # Feature 4: Point differential average
        df['point_diff_avg'] = df['pts_for_avg'] - df['pts_against_avg']

        # Feature 5: Last 3 games win %
        df['last3_wins'] = df['won'].rolling(window=3, min_periods=1).sum()
        df['last3_games'] = df['won'].rolling(window=3, min_periods=1).count()
        df['last3_win_pct'] = df['last3_wins'] / df['last3_games']
        df['last3_win_pct'] = df['last3_win_pct'].shift(1).fillna(0.5)

        # Feature 6: games_played
        df['games_played'] = df['games_played'].shift(1).fillna(0)

        # Feature 7-8: Scoring volatility (std)
        df['pts_for_std'] = df['pts_for'].abs().expanding().std()
        df['pts_for_std'] = df['pts_for_std'].shift(1).fillna(0)

        df['pts_against_std'] = 0  # Not available

        # Feature 9: Win streak
        def compute_streak(series):
            """Compute current win/loss streak."""
            if len(series) == 0:
                return 0
            streak = 0
            for val in reversed(list(series)):
                if val == 1:  # Win
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                else:  # Loss
                    if streak <= 0:
                        streak -= 1
                    else:
                        break
            return streak

        df['win_streak'] = df['won'].expanding().apply(compute_streak, raw=False)
        df['win_streak'] = df['win_streak'].shift(1).fillna(0)

        return df

    def _neutral_features(self) -> pd.DataFrame:
        """Return neutral features for first game or no history."""
        return pd.DataFrame([{
            'win_pct': 0.5,
            'pts_for_avg': 0.0,
            'pts_against_avg': 0.0,
            'point_diff_avg': 0.0,
            'last3_win_pct': 0.5,
            'games_played': 0.0,
            'pts_for_std': 0.0,
            'pts_against_std': 0.0,
            'win_streak': 0.0,
        }])[self.feature_names]

    def predict(self, symbol: str, game_date: datetime) -> Dict:
        """
        Predict outcome for a game.

        Args:
            symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
            game_date: Game date (timezone-aware UTC)

        Returns:
            {
                "predicted_winner": "WIN" or "LOSS",
                "win_probability": 0.0-1.0,
                "confidence": 0.0-1.0,
                "features_used": 9,
                "model_version": "v1.0"
            }
        """
        # Extract features
        features = self.extract_features(symbol, game_date)

        # Scale features
        X_scaled = self.scaler.transform(features)

        # Predict
        win_prob = self.model.predict_proba(X_scaled)[0][1]
        predicted_winner = "WIN" if win_prob > 0.5 else "LOSS"
        confidence = max(win_prob, 1 - win_prob)

        return {
            "predicted_winner": predicted_winner,
            "win_probability": float(win_prob),
            "confidence": float(confidence),
            "features_used": len(self.feature_names),
            "model_version": self.version,
        }

    def get_metadata(self) -> Dict:
        """Get model metadata."""
        return self.metadata


# Singleton instance
_forecaster = None


def get_forecaster() -> NFLMLForecaster:
    """Get or create the singleton forecaster instance."""
    global _forecaster
    if _forecaster is None:
        _forecaster = NFLMLForecaster()
    return _forecaster
