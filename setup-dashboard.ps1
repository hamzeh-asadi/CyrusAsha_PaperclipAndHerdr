# Windows launcher. CLI arguments override dashboard/.env; other keys are preserved.
param(
    [string]$PaperclipUrl,
    [string]$CompanyId,
    [string]$DashboardHost,
    [ValidateRange(1, 65535)][int]$DashboardPort,
    [ValidateRange(1, 3600)][int]$StartupTimeout = 180,
    [switch]$NoBrowser,
    [string]$PythonExe,
    [ValidatePattern('^3\.\d+$')][string]$PythonVersion,
    [switch]$ExistingOnly,
    [switch]$DiagnosePostgres,
    [string]$ConfigPath
)
$ErrorActionPreference = 'Stop'

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($DiagnosePostgres) {
        . (Join-Path $PSScriptRoot 'scripts/windows-postgres-check.ps1')
        Write-Host 'Read-only check. No setup, start/stop, repair or changes to data or lock files.'
        $result = Get-PaperclipDbCheck -ConfigPath $ConfigPath
        Write-Host "DB-CHECK: $result"
        Write-Host 'See docs/SETUP.en.md or docs/SETUP.fa.md (PostgreSQL). A match is not permission to start a second server.'
        exit 0 # a diagnostic report, not a readiness decision
    }
    if ($PSBoundParameters.ContainsKey('ConfigPath')) { throw '-ConfigPath selects an existing config for -DiagnosePostgres only.' }
    . (Join-Path $PSScriptRoot 'scripts/windows-python.ps1')
    . (Join-Path $PSScriptRoot 'scripts/windows-paperclip.ps1')
    $runtime = Resolve-DashboardPython -PythonExe $PythonExe -PythonVersion $PythonVersion
    $python = $runtime.Executable
    $appFile = Join-Path $PSScriptRoot 'dashboard/app.py'
    Write-Host "Using Python $($runtime.Version): $python"

    $envFile = Join-Path $PSScriptRoot 'dashboard/.env'
    $exists = Test-Path -LiteralPath $envFile
    $source = if ($exists) { $envFile } else { "$envFile.example" }
    $updates = @{}
    $keys = @{ PaperclipUrl='PAPERCLIP_API_URL'; CompanyId='PAPERCLIP_COMPANY_ID'; DashboardHost='DASHBOARD_HOST'; DashboardPort='DASHBOARD_PORT' }
    foreach ($name in $keys.Keys) {
        if ($PSBoundParameters.ContainsKey($name)) {
            $value = [string]$PSBoundParameters[$name]
            if ($value -match '[\r\n]') { throw "$name must be a single line." }
            $updates[$keys[$name]] = $value
        }
    }
    # Keep comments, API key, Herdr map and all unspecified settings on reruns.
    $lines = @(foreach ($line in [IO.File]::ReadAllLines($source)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=' -and $updates.ContainsKey($Matches[1])) { continue }
        $line
    })
    foreach ($key in $updates.Keys) { $lines += "$key=$($updates[$key])" }
    $baseUrl = $env:PAPERCLIP_API_URL
    foreach ($line in $lines) {
        if ($line -match '^\s*PAPERCLIP_API_URL\s*=(.*)$') { $baseUrl = $Matches[1].Trim().Trim('"').Trim("'") }
    }
    if (-not $baseUrl) { $baseUrl = 'http://localhost:3100' }
    $baseUrl = $baseUrl.TrimEnd('/')
    $uri = [uri]$baseUrl
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -notin 'http','https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw 'PAPERCLIP_API_URL must be an HTTP(S) base URL without credentials, query or fragment.'
    }

    Wait-PaperclipReady -BaseUrl $baseUrl -PythonExe $python -AppFile $appFile -ProjectRoot $PSScriptRoot -StartupTimeout $StartupTimeout -ExistingOnly:$ExistingOnly
    Write-Host "Paperclip ready at $baseUrl. The dashboard uses the only company, or the configured PAPERCLIP_COMPANY_ID."
    if (-not $exists -or $updates.Count) { [IO.File]::WriteAllLines($envFile, [string[]]$lines) }
    if (-not (Get-Command herdr -ErrorAction SilentlyContinue)) { Write-Host 'Herdr not found; terminal output is unavailable. Paperclip does not need Herdr.' }

    $appArgs = @($appFile)
    if (-not $NoBrowser) { $appArgs += '--open-browser' }
    & $python @appArgs
    exit $LASTEXITCODE
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
