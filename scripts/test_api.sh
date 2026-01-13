#!/bin/bash
# Test Polygon API with various timestamp formats

API_KEY="13pxjpTe80GhXDijoB_3s4QVbo6CBKN7"

echo "=== Test 1: Date string format ==="
curl -s "https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/2026-01-12/2026-01-13?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -20

echo ""
echo "=== Test 2: Unix seconds ==="
NOW=$(date +%s)
START=$((NOW - 7200))  # 2 hours ago
curl -s "https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/$START/$NOW?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -20

echo ""
echo "=== Test 3: BTCUSD (24/7 market) ==="
curl -s "https://api.polygon.io/v2/aggs/ticker/X:BTCUSD/range/5/minute/$START/$NOW?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -20

echo ""
echo "=== Test 4: XAUUSD ==="
curl -s "https://api.polygon.io/v2/aggs/ticker/C:XAUUSD/range/5/minute/$START/$NOW?adjusted=true&sort=desc&limit=5&apiKey=$API_KEY" | python3 -m json.tool 2>/dev/null | head -20
