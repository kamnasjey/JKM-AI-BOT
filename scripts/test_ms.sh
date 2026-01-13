#!/bin/bash
API_KEY="13pxjpTe80GhXDijoB_3s4QVbo6CBKN7"
NOW_S=$(date +%s)
NOW_MS=$((NOW_S * 1000))
START_MS=$((NOW_MS - 7200000))

echo "Testing with milliseconds: $START_MS to $NOW_MS"
curl -s "https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/$START_MS/$NOW_MS?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -15

echo ""
echo "Testing BTCUSD:"
curl -s "https://api.polygon.io/v2/aggs/ticker/X:BTCUSD/range/5/minute/$START_MS/$NOW_MS?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -15
