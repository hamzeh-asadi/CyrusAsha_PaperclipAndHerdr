function Start-LocalPaperclip([string]$ProjectRoot) {
    # Check the first Node on PATH, just as npm.cmd will; never invoke an array of paths.
    $node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node) { throw 'Install a current Node.js 24 LTS and reopen this terminal.' }
    $version = [version](& $node.Path -p 'process.versions.node')
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
    Start-PaperclipCommand -ProjectRoot $ProjectRoot
}

function Start-PaperclipCommand([string]$ProjectRoot) {
    # Retain the original process handle: Windows PowerShell 5.1's
    # Start-Process -PassThru can lose ExitCode on a quickly exiting child.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $env:ComSpec
    $info.Arguments = '/d /c npm.cmd start'
    $info.WorkingDirectory = $ProjectRoot
    $info.UseShellExecute = $false # inherit the console; no redirected pipe to fill
    return [Diagnostics.Process]::Start($info)
}

function Get-PaperclipState([string]$PythonExe, [string]$AppFile, [string]$BaseUrl, [int]$TimeoutSec) {
    # Use the dashboard's HTTP client, including its loopback proxy bypass and no-redirect policy.
    $state = & $PythonExe $AppFile --probe-paperclip $BaseUrl --probe-timeout $TimeoutSec
    if ($LASTEXITCODE -ne 0 -or $state -notin 'ok','starting','timeout','refused') {
        throw "Cannot verify $BaseUrl/api/health. Check the probe error above; not starting another server."
    }
    return $state
}

function Test-LocalPaperclipListener {
    # Check the OS, not a guessed error string: a timeout can mean either a slow
    # existing listener or no service at all. Only used for the default local port.
    try {
        foreach ($endpoint in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
            if ($endpoint.Port -eq 3100) { return $true }
        }
        return $false
    } catch { return $null } # unknown is not evidence that a timed-out port is free
}

function Wait-PaperclipReady([string]$BaseUrl, [string]$PythonExe, [string]$AppFile, [string]$ProjectRoot, [int]$StartupTimeout, [switch]$ExistingOnly) {
    $managed = -not $ExistingOnly -and $BaseUrl -in 'http://127.0.0.1:3100', 'http://localhost:3100'
    $proc = $null
    $lastState = 'not probed'
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        if ($proc -and $proc.HasExited) {
            $code = $proc.ExitCode
            $reason = if ($null -eq $code) { 'exit code unavailable' } else { "code $code" }
            throw "Paperclip exited ($reason). See the first server error above. For a PostgreSQL reuse refusal, run .\setup-dashboard.cmd -DiagnosePostgres. Do not remove postmaster.pid or start a second instance."
        }
        $remaining = $StartupTimeout - $timer.Elapsed.TotalSeconds
        if ($remaining -le 0) {
            $hint = if ($managed) { 'Inspect port 3100 with Get-NetTCPConnection -LocalPort 3100 -State Listen.' } else { 'Check the configured host/port.' }
            throw "Paperclip not ready at $BaseUrl/api/health after $StartupTimeout seconds (last probe: $lastState). $hint Check the Paperclip console. Dashboard was not started."
        }
        $seconds = [Math]::Min(5, [int][Math]::Ceiling($remaining))
        $state = Get-PaperclipState -PythonExe $PythonExe -AppFile $AppFile -BaseUrl $BaseUrl -TimeoutSec $seconds
        if ($state -eq 'ok') { return }
        if ($state -ne $lastState) { Write-Host "Waiting for Paperclip at $BaseUrl/api/health (probe: $state)..." }
        $lastState = $state
        if (-not $proc -and $state -in 'refused','timeout') {
            if ($managed) {
                $inUse = Test-LocalPaperclipListener
                $mayStart = if ($null -eq $inUse) { $state -eq 'refused' } else { -not $inUse }
                if ($mayStart) {
                    $proc = Start-LocalPaperclip -ProjectRoot $ProjectRoot
                    $timer.Restart() # npm ci happens before startup and is not part of the readiness timeout
                }
            } elseif ($state -eq 'refused') {
                throw "No Paperclip at $BaseUrl. Start that instance yourself or correct -PaperclipUrl. Not starting a local duplicate."
            }
        }
        $delay = [Math]::Min(2000, [Math]::Max(0, $StartupTimeout * 1000 - [int]$timer.ElapsedMilliseconds))
        Start-Sleep -Milliseconds ([int]$delay)
    }
}
