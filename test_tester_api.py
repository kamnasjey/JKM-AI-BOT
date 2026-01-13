import httpx
import json

payload = {
    "symbol": "XAUUSD",
    "detectors": ["break_retest", "fibo_retrace_confluence"],
    "entry_tf": "H1",
    "initial_capital": 10000
}

r = httpx.post(
    "http://localhost:8000/api/strategy-tester/run",
    json=payload,
    headers={"x-internal-api-key": "3d2ee6bbbb787c90ebc25f39b26eca1569c8dde81ab4be7d908df477c9d1bda6"}
)
print("Status:", r.status_code)
print("Response:", r.text[:1000] if r.text else "empty")
