# Windows launcher. CLI arguments override dashboard/.env; other keys are preserved.
param(
    [string]$PaperclipUrl,
    [string]$CompanyId,
    [string]$DashboardHost,
    [ValidateRange(1, 65535)][int]$DashboardPort,
    [ValidateRange(1, 3600)][int]$StartupTimeout = 180,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'

function Get-PaperclipState([string]$baseUrl) {
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 3 -MaximumRedirection 0
    } catch {
        # Only an absent listener warrants starting a process. Do not start a
        # second instance on an HTTP error, redirect, timeout or auth failure.
        for ($err = $_.Exception; $err; $err = $err.InnerException) {
            if (($err -is [Net.Sockets.SocketException] -and $err.SocketErrorCode -eq 'ConnectionRefused') -or
                ($err -is [Net.WebException] -and $err.Status -eq 'ConnectFailure')) { return 'stopped' }
        }
        throw "Cannot read $baseUrl/api/health : $($_.Exception.Message)"
    }
    if ($health.status -in 'ok', 'starting') { return $health.status }
    throw "Unexpected response from $baseUrl/api/health. Check PAPERCLIP_API_URL and the process using that port."
}

function Start-LocalPaperclip {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { throw 'Install a current Node.js 24 LTS and reopen this terminal.' }
    $version = [version](& $node.Source -p 'process.versions.node')
    if ($version -lt [version]'24.15.0' -or $version.Major -eq 25) {
        throw "Node $version is not supported by the locked dependencies. Install Node 24 LTS (24.15+) or 26+."
    }
    $expected = (Get-Content -Raw package.json | ConvertFrom-Json).dependencies.paperclipai
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm.cmd is not in PATH. Check the Node.js installation.' }
    if ([version](& npm.cmd --version) -lt [version]'11.16.0') { throw 'Use npm 11.16+ for project install-script support. After upgrading Node run npm.cmd install -g npm@11, then reopen the terminal.' }
    $ready = Test-Path 'node_modules/.bin/paperclipai.cmd'
    if ($ready) {
        # A matching CLI version alone does not guarantee the security patch
        # overrides are installed. npm ls is local-only; avoid npm.ps1 policy.
        & $env:ComSpec /d /c 'npm.cmd ls paperclipai better-auth @vercel/cli-config --all --json >nul 2>&1'
        $ready = $LASTEXITCODE -eq 0
    }
    if (-not $ready) {
        Write-Host "Installing the project's paperclipai $expected (first download may take several minutes)..."
        & npm.cmd ci | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. See the npm error above. Paperclip was not started.' }
    }
    Write-Host 'Starting Paperclip: npm.cmd start (logs in this console)'
    # Only fixed commands go through cmd; user paths/URLs are never interpolated.
    Start-Process -FilePath $env:ComSpec -ArgumentList '/d', '/c', 'npm.cmd start' -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru
}

Push-Location -LiteralPath $PSScriptRoot
try {
    # python.exe can be a Windows Store alias, so test the interpreter itself.
    $python = $null
    foreach ($name in 'py.exe', 'python.exe') {
        $candidate = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if (-not $candidate) { continue }
        $pyArgs = @()
        if ($name -eq 'py.exe') { $pyArgs += '-3' }
        & $candidate.Source @pyArgs -c 'import sys; sys.exit(sys.version_info < (3, 10))'
        if ($LASTEXITCODE -eq 0) { $python = $candidate.Source; break }
    }
    if (-not $python) { throw 'Python 3.10+ is required for the dashboard. Paperclip alone can be run with npm start.' }

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

    $state = Get-PaperclipState $baseUrl
    $proc = $null
    if ($state -eq 'stopped') {
        if ($baseUrl -notin 'http://localhost:3100', 'http://127.0.0.1:3100') {
            throw "No Paperclip at $baseUrl. Start that instance yourself or correct -PaperclipUrl. Not starting a local duplicate."
        }
        $proc = Start-LocalPaperclip
    }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($state -ne 'ok') {
        if ($proc -and $proc.HasExited) { throw "Paperclip exited (code $($proc.ExitCode)). See the error above; try npm.cmd start and npm.cmd run doctor." }
        if ($timer.Elapsed.TotalSeconds -ge $StartupTimeout) { throw "Paperclip not ready at $baseUrl after $StartupTimeout seconds. Check the URL/port printed by Paperclip. Dashboard was not started." }
        Start-Sleep -Seconds 2
        $state = Get-PaperclipState $baseUrl
    }
    Write-Host "Paperclip ready at $baseUrl. The dashboard uses the only company, or the configured PAPERCLIP_COMPANY_ID."
    if (-not $exists -or $updates.Count) { [IO.File]::WriteAllLines($envFile, [string[]]$lines) }
    if (-not (Get-Command herdr -ErrorAction SilentlyContinue)) { Write-Host 'Herdr not found; terminal output is unavailable. Paperclip does not need Herdr.' }

    $appArgs = @('dashboard/app.py')
    if (-not $NoBrowser) { $appArgs += '--open-browser' }
    & $python @pyArgs @appArgs
    exit $LASTEXITCODE
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
