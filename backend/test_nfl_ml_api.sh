#!/bin/bash
# Test NFL ML API for all NFC East teams

echo "Testing NFL ML API v2.0 for all NFC East teams..."

for team in "NFL:DAL_COWBOYS" "NFL:NYG_GIANTS" "NFL:PHI_EAGLES" "NFL:WSH_COMMANDERS"; do
  echo ""
  echo "=== $team ==="
  curl -s "http://127.0.0.1:9000/forecast/nfl/ml/game?team_symbol=$team&game_date=2024-12-15T18:00:00Z"
  echo ""
done

echo ""
echo "All tests complete!"
