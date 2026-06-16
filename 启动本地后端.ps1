$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "backend\uvicorn.pid"
$OutLog = Join-Path $Root "backend\uvicorn.out.log"
$ErrLog = Join-Path $Root "backend\uvicorn.err.log"
$HealthUrl = "http://127.0.0.1:8000/health"

function Test-Health {
  try {
    $result = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    return $result.status -eq "ok"
  } catch {
    return $false
  }
}

if (Test-Health) {
  Write-Host "Backend is already running: $HealthUrl" -ForegroundColor Green
  exit 0
}

$env:APP_ENV = "local"
$env:CORS_ALLOW_ORIGINS = "*"
$env:HAIR_AI_DB_PATH = Join-Path $Root "hair_ai_dev.sqlite3"
$env:DATABASE_URL = ""
$env:PAYMENT_PROVIDER = "mock"
$env:TEMP_STORAGE_PROVIDER = "mock"
$env:FEISHU_SYNC_PROVIDER = "mock"
$env:DIFY_BASE_URL = ""
$env:DIFY_API_KEY = ""
$env:PYTHONPATH = "backend"

if (Test-Path $OutLog) { Remove-Item -LiteralPath $OutLog -Force }
if (Test-Path $ErrLog) { Remove-Item -LiteralPath $ErrLog -Force }

$DbPath = Join-Path $Root "hair_ai_dev.sqlite3"
$cmd = "set APP_ENV=local&& set CORS_ALLOW_ORIGINS=*&& set HAIR_AI_DB_PATH=$DbPath&& set DATABASE_URL=&& set PAYMENT_PROVIDER=mock&& set TEMP_STORAGE_PROVIDER=mock&& set FEISHU_SYNC_PROVIDER=mock&& set DIFY_BASE_URL=&& set DIFY_API_KEY=&& set PYTHONPATH=backend&& python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend > `"$OutLog`" 2> `"$ErrLog`""

$process = Start-Process `
  -FilePath "cmd.exe" `
  -ArgumentList @("/c", $cmd) `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -PassThru

Set-Content -Path $PidFile -Value $process.Id -Encoding ASCII

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 500
  if (Test-Health) {
    Write-Host "Backend started: $HealthUrl" -ForegroundColor Green
    Write-Host "PID: $($process.Id)"
    Write-Host "Logs: backend\uvicorn.out.log / backend\uvicorn.err.log"
    exit 0
  }
}

Write-Host "Backend did not become healthy in time." -ForegroundColor Red
Write-Host "Check logs: backend\uvicorn.err.log" -ForegroundColor Yellow
exit 1
