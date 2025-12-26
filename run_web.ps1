param(
	[switch]$Demo,
	[switch]$Live
)

Set-Location -LiteralPath $PSScriptRoot

if ($Demo -and $Live) {
	throw "Choose only one of -Demo or -Live"
}

if ($Demo) {
	$env:IG_IS_DEMO = "true"
	Write-Host "Starting JKM Trading AI Web (DEMO) on http://127.0.0.1:8000"
} elseif ($Live) {
	$env:IG_IS_DEMO = "false"
	Write-Host "Starting JKM Trading AI Web (LIVE) on http://127.0.0.1:8000"
} else {
	Write-Host "Starting JKM Trading AI Web on http://127.0.0.1:8000"
}

& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn web_app:app --reload --host 127.0.0.1 --port 8000
