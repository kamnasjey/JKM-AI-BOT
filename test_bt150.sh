#!/bin/bash
curl -s -X POST http://127.0.0.1:8000/api/backtest \
  -H "Content-Type: application/json" \
  -H "x-internal-api-key: 3d2ee6bbbb787c90ebc25f39b26eca1569c8dde81ab4be7d908df477c9d1bda6" \
  -d '{"days": 150}'
