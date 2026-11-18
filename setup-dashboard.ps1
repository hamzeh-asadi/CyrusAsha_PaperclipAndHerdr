# Setup Unified Dashboard for Paperclip+Herdr
# Requires: Python 3.10+, Paperclip running, Herdr installed
# Run with: powershell -ExecutionPolicy Bypass -File .\setup-dashboard.ps1

param(
    [string]$PaperclipUrl = "http://localhost:3100",
    [string]$CompanyId = "",
    [string]$DashboardHost = "0.0.0.0",
    [int]$DashboardPort = 8000
)

$ErrorActionPreference = "Continue"

Write-Host "=== Unified Dashboard Setup ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Python
Write-Host "1. Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "  Please install Python 3.10+ from python.org" -ForegroundColor Red
    exit 1
}

# Step 2: Check Paperclip Service
Write-Host "2. Checking Paperclip Service..." -ForegroundColor Yellow
$paperclipRunning = $false
$companies = $null

try {
    $response = Invoke-RestMethod -Uri "$PaperclipUrl/api/companies" -Method Get -TimeoutSec 3
    Write-Host "  Paperclip is already running on $PaperclipUrl" -ForegroundColor Green
    $paperclipRunning = $true
    $companies = $response
} catch {
    Write-Host "  Paperclip is not responding on $PaperclipUrl" -ForegroundColor DarkYellow
    Write-Host "  Starting Paperclip via npx in a new window..." -ForegroundColor Yellow
    
    # Launch Paperclip in a separate visible CMD window so it doesn't hang setup
    Start-Process cmd.exe -ArgumentList "/c npx --yes paperclipai@latest run"
    
    Write-Host "  Waiting for Paperclip server to initialize..." -ForegroundColor Yellow
    $maxWait = 25
    $waited = 0
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 3
        $waited += 3
        try {
            $response = Invoke-RestMethod -Uri "$PaperclipUrl/api/companies" -Method Get -TimeoutSec 3
            Write-Host "  Paperclip is now online!" -ForegroundColor Green
            $paperclipRunning = $true
            $companies = $response
            break
        } catch {
            Write-Host "  Waiting for Paperclip server... ($waited/$maxWait seconds)" -ForegroundColor DarkYellow
        }
    }
    
    if (-not $paperclipRunning) {
        Write-Host ""
        Write-Host "  [NOTICE] Paperclip server did not start automatically within $maxWait seconds." -ForegroundColor Red
        Write-Host "  If this is your first time, run onboarding manually in another window:" -ForegroundColor Yellow
        Write-Host "    npx paperclipai@latest onboard --yes" -ForegroundColor Cyan
        Write-Host "  Or start the server with:" -ForegroundColor Yellow
        Write-Host "    npx paperclipai run" -ForegroundColor Cyan
        Write-Host ""
    }
}

if ($paperclipRunning -and $companies) {
    Write-Host "  Available Companies:" -ForegroundColor Cyan
    if ($companies.Count -gt 0) {
        $companies | ForEach-Object { Write-Host "    - ID: $($_.id) | Name: $($_.name)" }
    } else {
        Write-Host "    (No companies found. Create one at $PaperclipUrl)" -ForegroundColor DarkYellow
    }
}

# Step 3: Check Herdr
Write-Host "3. Checking Herdr..." -ForegroundColor Yellow
$herdrInstalled = $false
try {
    $herdrPath = Get-Command herdr -ErrorAction SilentlyContinue
    if ($herdrPath) {
        Write-Host "  Herdr is installed ($($herdrPath.Source))" -ForegroundColor Green
        $herdrInstalled = $true
    } else {
        Write-Host "  Herdr command not found in PATH" -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "  Herdr check failed" -ForegroundColor DarkYellow
}

if (-not $herdrInstalled) {
    Write-Host "  Note: Herdr can be installed via: powershell -ExecutionPolicy Bypass -c `"irm https://herdr.dev/install.ps1 | iex`"" -ForegroundColor DarkYellow
}

# Step 4: Select or Prompt for Company ID
if ($paperclipRunning -and $companies -and (-not $CompanyId)) {
    if ($companies.Count -eq 1) {
        $CompanyId = $companies[0].id
        Write-Host "  Auto-selected company: $($companies[0].name) ($CompanyId)" -ForegroundColor Green
    } elseif ($companies.Count -gt 1) {
        Write-Host ""
        Write-Host "Please enter the Company ID from above (or press Enter for default):" -ForegroundColor Cyan
        $inputId = Read-Host "Company ID"
        if ($inputId) {
            $CompanyId = $inputId.Trim()
        } else {
            $CompanyId = $companies[0].id
        }
    }
}

if (-not $CompanyId) {
    $CompanyId = "856affb4-69f1-44cb-a690-e4c2e6b2769d"
}

# Step 5: Create/Update .env file
Write-Host "5. Creating configuration..." -ForegroundColor Yellow
$envDir = Join-Path $PSScriptRoot "dashboard"
if (-not (Test-Path $envDir)) {
    New-Item -ItemType Directory -Path $envDir -Force | Out-Null
}

$envFile = Join-Path $envDir ".env"
$envContent = @"
PAPERCLIP_API_URL=$PaperclipUrl
PAPERCLIP_COMPANY_ID=$CompanyId
HERDR_HOST=localhost
HERDR_PORT=50800
AGENT_PING_TIMEOUT=2000
DASHBOARD_HOST=$DashboardHost
DASHBOARD_PORT=$DashboardPort
"@

Set-Content -Path $envFile -Value $envContent -Encoding UTF8
Write-Host "  Saved configuration to $envFile" -ForegroundColor Green

# Step 6: Start the dashboard
Write-Host ""
Write-Host "6. Starting Dashboard..." -ForegroundColor Yellow

$mainFile = Join-Path $envDir "app.py"
$pythonProc = Start-Process python -ArgumentList "`"$mainFile`"" -NoNewWindow -PassThru

# Wait until the server actually answers before opening the browser
$healthUrl = "http://localhost:$DashboardPort/health"
$ready = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1
    if ($pythonProc.HasExited) { break }
    try {
        Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Write-Host "  Waiting for dashboard server... ($i/15)" -ForegroundColor DarkYellow
    }
}

if ($ready) {
    Write-Host "  Dashboard is up: http://localhost:$DashboardPort" -ForegroundColor Green
    Start-Process "http://localhost:$DashboardPort"
    Wait-Process -Id $pythonProc.Id
} else {
    Write-Host "  [ERROR] Dashboard server did not answer on $healthUrl" -ForegroundColor Red
    Write-Host "  Start it manually with: python `"$mainFile`"" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Dashboard stopped." -ForegroundColor Yellow
