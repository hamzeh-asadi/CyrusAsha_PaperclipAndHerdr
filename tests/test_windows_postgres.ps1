# PowerShell 5.1 regression tests. Only files under a unique temp fixture are used.
param([switch]$WithLocalCluster)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$fixture = Join-Path $tempRoot ('desk pg ' + [guid]::NewGuid())
$cfg = Join-Path $fixture 'existing config.json'
$data = Join-Path $fixture 'existing db'
$oldConfig, $oldUrl = $env:PAPERCLIP_CONFIG, $env:DATABASE_URL
New-Item -ItemType Directory -Path $fixture | Out-Null
Push-Location $fixture
try {
    $env:PAPERCLIP_CONFIG = Join-Path $fixture 'other instance.json'
    $env:DATABASE_URL = $null
    Copy-Item (Join-Path $repo 'scripts') . -Recurse
    Copy-Item (Join-Path $repo 'setup-dashboard.ps1') .
    . .\scripts\windows-postgres-check.ps1
    if ((Find-DbCheckConfig) -cne $env:PAPERCLIP_CONFIG -or (Find-DbCheckConfig $cfg) -cne $cfg) { throw 'Wrong config precedence' }
    function Assert-Result([string]$Expected) {
        $actual = Get-PaperclipDbCheck -ConfigPath $cfg
        if ($actual -cne $Expected) { throw "Expected $Expected, got $actual" }
    }
    Assert-Result 'config-not-found'
    [IO.File]::WriteAllText($cfg, 'not json')
    Assert-Result 'config-unreadable'
    $config = @{database=@{mode='embedded-postgres';embeddedPostgresDataDir=$data;embeddedPostgresPort=54329};server=@{port=3100}}
    [IO.File]::WriteAllText($cfg, ($config | ConvertTo-Json))
    $env:DATABASE_URL = 'external-test-only'
    Assert-Result 'not-an-embedded-config'
    $env:DATABASE_URL = $null
    Assert-Result 'no-pid-file'
    if (Test-Path $data) { throw 'Diagnostic created a data directory' }
    # The diagnostic entry point must work with no Python, npm install, or dashboard/.env.
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-dashboard.ps1 -DiagnosePostgres -ConfigPath $cfg
    if ($LASTEXITCODE -ne 0 -or $out -notcontains 'DB-CHECK: no-pid-file' -or (Test-Path 'dashboard/.env')) { throw 'Diagnostic unexpectedly bootstrapped setup' }

    New-Item -ItemType Directory -Path $data | Out-Null
    $lock = Join-Path $data 'postmaster.pid'
    & {
        function Get-DbCheckSqlResult { throw 'Unexpected SQL probe' }
        [IO.File]::WriteAllText($lock, "1`n$data`n0`n99999`n")
        Assert-Result 'invalid-pid-file'
        [IO.File]::WriteAllText($lock, "$PID`n$data`n0`n54330`n")
        Assert-Result 'pid-not-postgres' # test process, not PostgreSQL; never signal or delete
        function Get-DbCheckOwner { return 'listener-owner-differs' }
        Assert-Result 'listener-owner-differs'
    }
    & {
        # No SQL driver in this fixture yet. Divergent paths must fail before import/connect.
        function Get-DbCheckOwner { return 'postgres-listener' }
        [IO.File]::WriteAllText($lock, "$PID`n$fixture`n0`n54330`n")
        Assert-Result 'pid-file-dir-differs'
        [IO.File]::WriteAllText($lock, "$PID`n$data`n0`n54330`n")
        Assert-Result 'probe-unavailable'
    }
    $before = (Get-FileHash $lock).Hash
    & {
        function Get-DbCheckOwner([int]$OwnerPid,[int]$Port) {
            if ($OwnerPid -ne $PID -or $Port -ne 54330) { throw 'Did not use the PID-file port' }
            return 'postgres-listener'
        }
        function Get-DbCheckSqlResult([int]$Port,[string]$DataDir,[string]$LockDir) {
            if ($DataDir -cne $data -or $LockDir -cne $data -or $Port -ne 54330) { throw 'Wrong SQL probe target' }
            return 'sql-auth-failed'
        }
        Assert-Result 'sql-auth-failed'
    }
    if ((Get-FileHash $lock).Hash -ne $before) { throw 'Diagnostic modified the lock' }

    if ($WithLocalCluster) {
        # CI-only integration: never use PGDATA, a service, or an operator's existing cluster.
        if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:PGBIN) { throw 'Run the disposable cluster test on the Windows CI image only.' }
        $real = Join-Path $fixture 'isolated real db'
        $config.database.embeddedPostgresDataDir = $real
        [IO.File]::WriteAllText($cfg, ($config | ConvertTo-Json))
        $driver = & node.exe -p "require(process.argv[1]).packages['node_modules/postgres'].version" (Join-Path $repo 'package-lock.json')
        if ($LASTEXITCODE -ne 0 -or $driver -notmatch '^\d+\.\d+\.\d+$') { throw 'Missing locked SQL client version' }
        & npm.cmd install --prefix $fixture --ignore-scripts --no-audit --no-fund "postgres@$driver" | Out-Host
        if ($LASTEXITCODE) { throw 'Could not install the pinned SQL driver into the test fixture' }
        $pw = Join-Path $fixture 'init-password'
        [IO.File]::WriteAllText($pw, "paperclip`n") # disposable embedded test role only
        & (Join-Path $env:PGBIN 'initdb.exe') -D $real -U paperclip -A scram-sha-256 "--pwfile=$pw" --no-sync | Out-Host
        if ($LASTEXITCODE) { throw 'Failed to initialize isolated fixture' }
        $tcp = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
        $tcp.Start(); $port = $tcp.LocalEndpoint.Port; $tcp.Stop()
        $ctl = Join-Path $env:PGBIN 'pg_ctl.exe'
        & $ctl -D $real -l (Join-Path $fixture 'pg.log') -o "-h 127.0.0.1 -p $port" -w start
        if ($LASTEXITCODE) { throw 'Failed to start isolated fixture' }
        try {
            Assert-Result 'server-dir-matches'
            # Reproduce the two distinct reasons for Paperclip's identical refusal.
            # Only the *synthetic* lock in the other fixture directory is written.
            $postmaster = [IO.File]::ReadAllLines((Join-Path $real 'postmaster.pid'))[0]
            [IO.File]::WriteAllText($lock, "$postmaster`n$data`n0`n$port`n")
            $config.database.embeddedPostgresDataDir = $data
            [IO.File]::WriteAllText($cfg, ($config | ConvertTo-Json))
            Assert-Result 'server-dir-differs'
            $alternateCase = Join-Path $fixture 'ISOLATED REAL DB'
            if ((Get-DbCheckSqlResult $port $alternateCase $alternateCase) -cne 'same-dir-different-spelling') {
                throw 'Failed to distinguish two spellings of the same NTFS directory'
            }
            $config.database.embeddedPostgresDataDir = $real
            [IO.File]::WriteAllText($cfg, ($config | ConvertTo-Json))
            # Refuse only test logins in this disposable CI cluster, not a password reset.
            $hba = Join-Path $real 'pg_hba.conf'
            [IO.File]::WriteAllText($hba, "host postgres paperclip 127.0.0.1/32 reject`n" + [IO.File]::ReadAllText($hba))
            & $ctl -D $real reload
            if ($LASTEXITCODE) { throw 'Failed to reload disposable test rule' }
            Assert-Result 'sql-auth-failed'
        } finally {
            & $ctl -D $real -m smart -w stop
            if ($LASTEXITCODE) { throw 'Fixture did not stop cleanly' }
        }
    }
    Write-Host 'Read-only PostgreSQL checks passed.'
} finally {
    Pop-Location
    $env:PAPERCLIP_CONFIG, $env:DATABASE_URL = $oldConfig, $oldUrl
    # Do not clean up a live cluster, even in a disposable CI sandbox.
    if (-not (Test-Path -LiteralPath (Join-Path $fixture 'isolated real db/postmaster.pid'))) {
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
}
