$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
  param([string]$Step)
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE"
  }
}

Write-Host "== Hair AI acceptance check ==" -ForegroundColor Cyan

Write-Host "`n1. Check miniapp JSON" -ForegroundColor Cyan
@'
import json
from pathlib import Path

files = list(Path("miniapp-customer").rglob("*.json")) + list(Path("miniapp-merchant").rglob("*.json"))
for file in files:
    json.loads(file.read_text(encoding="utf-8"))
print(f"JSON OK: {len(files)} files")
'@ | python -
Assert-LastExitCode "Miniapp JSON check"

Write-Host "`n1.1 Check WXML template safety" -ForegroundColor Cyan
@'
from pathlib import Path

bad = []
for file in list(Path("miniapp-customer").rglob("*.wxml")) + list(Path("miniapp-merchant").rglob("*.wxml")):
    text = file.read_text(encoding="utf-8")
    if ".join(" in text:
        bad.append(str(file))
    if "Services()" in text or "visibleServices()" in text:
        bad.append(str(file))
if bad:
    raise SystemExit("WXML should not call JS methods directly: " + ", ".join(bad))
print("WXML OK: no direct JS method calls")
'@ | python -
Assert-LastExitCode "WXML template safety check"

Write-Host "`n2. Run backend tests" -ForegroundColor Cyan
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -q
Assert-LastExitCode "Backend tests"

Write-Host "`n3. Run end-to-end acceptance" -ForegroundColor Cyan
python backend/scripts/acceptance_check.py
Assert-LastExitCode "End-to-end acceptance"

Write-Host "`n4. Validate Dify result contract" -ForegroundColor Cyan
python backend/scripts/validate_dify_result.py backend/fixtures/dify_success_result.json
Assert-LastExitCode "Dify result contract validation"

try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
  if ($health.status -eq "ok") {
    Write-Host "`n5. Run live HTTP miniapp smoke" -ForegroundColor Cyan
    python backend/scripts/live_miniapp_smoke.py http://127.0.0.1:8000
    Assert-LastExitCode "Live HTTP miniapp smoke"
  }
} catch {
  Write-Host "`n5. Skip live HTTP miniapp smoke because backend is not running." -ForegroundColor Yellow
}

Write-Host "`nAll checks passed." -ForegroundColor Green
