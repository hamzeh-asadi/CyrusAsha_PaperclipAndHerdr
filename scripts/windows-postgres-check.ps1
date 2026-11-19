# Read-only triage of the embedded cluster. No bootstrap, doctor/repair, .env
# import, service control or lock-file changes. Run from the project root.
function Resolve-DbCheckPath([string]$Value) {
    if ($Value -ceq '~') { return $HOME }
    if ($Value.StartsWith('~/')) { $Value = Join-Path $HOME $Value.Substring(2) }
    # Keep the original spelling (including 8.3 names); Node's path.resolve,
    # not .NET's expansion or PowerShell's case-insensitive -eq, is the guard.
    return [IO.Path]::Combine($PWD.Path, $Value)
}

function Find-DbCheckConfig([string]$ConfigPath) {
    if ($ConfigPath) { return Resolve-DbCheckPath $ConfigPath }
    if ($env:PAPERCLIP_CONFIG) { return Resolve-DbCheckPath $env:PAPERCLIP_CONFIG }
    # Same precedence as the pinned CLI: nearest .paperclip/config.json,
    # otherwise PAPERCLIP_HOME/instances/<id>/config.json.
    for ($dir = [IO.DirectoryInfo]$PWD.Path; $dir; $dir = $dir.Parent) {
        $candidate = [IO.Path]::Combine($dir.FullName, '.paperclip', 'config.json')
        if ([IO.File]::Exists($candidate)) { return $candidate }
    }
    $root = if (-not [string]::IsNullOrWhiteSpace($env:PAPERCLIP_HOME)) { Resolve-DbCheckPath $env:PAPERCLIP_HOME.Trim() } else { Join-Path $HOME '.paperclip' }
    $instance = if (-not [string]::IsNullOrWhiteSpace($env:PAPERCLIP_INSTANCE_ID)) { $env:PAPERCLIP_INSTANCE_ID.Trim() } else { 'default' }
    if ($instance -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid PAPERCLIP_INSTANCE_ID. Supply the Config: path from the failed start.' }
    return [IO.Path]::Combine($root, 'instances', $instance, 'config.json')
}

function Get-DbCheckOwner([int]$OwnerPid, [int]$Port) {
    try { $proc = Get-Process -Id $OwnerPid -ErrorAction Stop } catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return 'pid-not-running' }
        return 'owner-unverified'
    }
    if ($proc.ProcessName -notin 'postgres','postmaster') { return 'pid-not-postgres' }
    try {
        $rows = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
            $_.LocalPort -eq $Port -and $_.LocalAddress -in '127.0.0.1','0.0.0.0','::','::ffff:127.0.0.1'
        })
    } catch { return 'listener-unverified' }
    if (-not $rows.Count) { return 'no-loopback-listener' }
    foreach ($row in $rows) { if ($row.OwningProcess -ne $OwnerPid) { return 'listener-owner-differs' } }
    return 'postgres-listener'
}

function Get-DbCheckSqlResult([int]$Port, [string]$DataDir, [string]$LockDir) {
    $node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node) { return 'probe-unavailable' }
    if ($LockDir -notmatch '^[a-z]:[\\/]' -or $LockDir -match '["\x00-\x1f]') { return 'pid-file-dir-differs' }
    # Preserve path.resolve semantics and avoid a trailing backslash escaping
    # the native closing quote for paths containing spaces on PowerShell 5.1.
    if ($DataDir -match '[\\/]$') { $DataDir += '.' }
    if ($LockDir -match '[\\/]$') { $LockDir += '.' }
    # No URL, external database credentials, query text or executable comes from config.
    $probe = Join-Path $PSScriptRoot 'postgres-directory-check.mjs'
    try { $result = & $node.Path $probe $Port $DataDir $LockDir 2>$null } catch { return 'probe-unavailable' }
    $allowed = 'pid-file-dir-differs','dir-identity-unverified','server-dir-matches','server-dir-differs','same-dir-different-spelling',
               'sql-auth-failed','sql-not-ready','sql-unavailable','sql-timeout','probe-unavailable'
    if ($LASTEXITCODE -ne 0 -or $result -isnot [string] -or -not $allowed.Contains($result)) { return 'probe-unavailable' }
    return $result
}

function Show-DbCheckPort([string]$Label, $Value) {
    [int]$n = 0
    if ([int]::TryParse([string]$Value, [ref]$n) -and $n -ge 1 -and $n -le 65535) { Write-Host "${Label}: $n" }
}

function Get-PaperclipDbCheck([string]$ConfigPath) {
    $config = Find-DbCheckConfig $ConfigPath
    Write-Host "Config inspected (compare with Paperclip's Config: line): $config"
    try { $settings = [IO.File]::ReadAllText($config) | ConvertFrom-Json -ErrorAction Stop }
    catch [IO.FileNotFoundException] { return 'config-not-found' }
    catch [IO.DirectoryNotFoundException] { return 'config-not-found' }
    catch { return 'config-unreadable' }
    $db = $settings.database
    if ($env:DATABASE_URL -or $db.mode -ne 'embedded-postgres') { return 'not-an-embedded-config' }
    if (-not ($db.embeddedPostgresDataDir -is [string]) -or -not $db.embeddedPostgresDataDir.Trim()) { return 'data-dir-unspecified' }
    try { $dataDir = Resolve-DbCheckPath $db.embeddedPostgresDataDir } catch { return 'data-dir-unsupported' }
    if ($dataDir -notmatch '^[a-z]:[\\/]') { return 'data-dir-unsupported' } # local drive paths only
    Write-Host "Configured data directory: $dataDir"
    # Ports are hints, not endpoints to contact. Never echo arbitrary config values.
    Show-DbCheckPort 'API port in config' $settings.server.port
    Show-DbCheckPort 'DB port in config' $db.embeddedPostgresPort
    $lock = [IO.Path]::Combine($dataDir, 'postmaster.pid')
    try { $lines = [IO.File]::ReadAllText($lock).Split([char]10) } # same LF split as the server
    catch [IO.FileNotFoundException] { return 'no-pid-file' }
    catch [IO.DirectoryNotFoundException] { return 'no-pid-file' }
    catch { return 'pid-file-unreadable' }
    [int]$ownerPid = 0
    [int]$port = 0
    if ($lines.Count -lt 4 -or -not [int]::TryParse($lines[0], [ref]$ownerPid) -or $ownerPid -le 0 -or
        -not [int]::TryParse($lines[3], [ref]$port) -or $port -lt 1 -or $port -gt 65535 -or -not $lines[1]) { return 'invalid-pid-file' }
    Write-Host "PID from lock: $ownerPid; actual DB port from lock: $port"
    $owner = Get-DbCheckOwner $ownerPid $port
    if ($owner -ne 'postgres-listener') { return $owner }
    return Get-DbCheckSqlResult $port $dataDir $lines[1]
}
