# One-command start for Windows PowerShell.
#   .\dev.ps1           API on :8000 + Vite dev server on :5173 (hot reload)
#   .\dev.ps1 -Single   build the frontend once and serve everything from :8000
# If scripts are blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
param([switch]$Single)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "backend\.venv")) {
    Write-Host "Creating backend\.venv ..."
    py -3.12 -m venv backend\.venv 2>$null
    if (-not $?) { python -m venv backend\.venv }
    & backend\.venv\Scripts\python.exe -m pip install --upgrade pip
    & backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
}
if (-not (Test-Path "frontend\node_modules")) { Push-Location frontend; npm ci; Pop-Location }

$py = Resolve-Path "backend\.venv\Scripts\python.exe"
if ($Single) {
    Push-Location frontend; npm run build; Pop-Location
    Write-Host "Open http://127.0.0.1:8000"
    Push-Location backend; & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000; Pop-Location
    exit
}

$api = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--reload","--reload-dir","app","--host","127.0.0.1","--port","8000" -WorkingDirectory "backend" -PassThru -NoNewWindow
Write-Host "API  http://127.0.0.1:8000/docs"
Write-Host "App  http://127.0.0.1:5173"
try { Push-Location frontend; npm run dev -- --host 127.0.0.1 }
finally { Pop-Location; if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force } }
