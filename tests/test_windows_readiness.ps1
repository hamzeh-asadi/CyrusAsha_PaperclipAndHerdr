# Offline readiness state machine (no sockets, installations or processes started).
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/windows-paperclip.ps1')

function Test-Readiness([string[]]$States, [int]$Starts = 0, $Listener = $true,
                        [string]$Url = 'http://localhost:3100', [string]$ErrorLike, [switch]$Deadline, [switch]$ChildExit) {
    $pending = [Collections.Queue]::new()
    foreach ($state in $States) { $pending.Enqueue($state) }
    $observed = @{Starts=0}
    function Get-PaperclipState {
        if ($pending.Count -eq 0) { throw 'Unexpected extra probe' }
        return $pending.Dequeue()
    }
    function Test-LocalPaperclipListener { return $Listener }
    function Start-LocalPaperclip {
        $observed.Starts++
        return [pscustomobject]@{HasExited=[bool]$ChildExit; ExitCode=77}
    }
    function Start-Sleep {
        if ($Deadline) { Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 1050 }
    }
    $limit = if ($Deadline) { 1 } else { 180 }
    $message = $null
    try { Wait-PaperclipReady -BaseUrl $Url -StartupTimeout $limit } catch { $message = $_.Exception.Message }
    if (($ErrorLike -and $message -notlike $ErrorLike) -or (-not $ErrorLike -and $message)) { throw "Unexpected outcome for ${States}: $message" }
    if ($pending.Count -or $observed.Starts -ne $Starts) { throw "Wrong probe/start count for ${States}: $($observed.Starts) start(s)." }
}

Test-Readiness -States 'ok'
Test-Readiness -States 'timeout','starting','ok' # existing listener; no duplicate
Test-Readiness -States 'timeout','ok' -Listener $null # unknown is not a free port
Test-Readiness -States 'refused','timeout','starting','ok' -Listener $false -Starts 1
Test-Readiness -States 'timeout','refused','ok' -Listener $false -Starts 1
Test-Readiness -States 'timeout','ok' -Url 'http://localhost:3200' -Listener $false
Test-Readiness -States 'refused' -Url 'http://localhost:3200' -Listener $false -ErrorLike 'No Paperclip at *'
Test-Readiness -States 'timeout' -Deadline -ErrorLike 'Paperclip not ready *last probe: timeout*'
Test-Readiness -States 'refused' -Listener $false -Starts 1 -ChildExit -ErrorLike 'Paperclip exited (code 77)*'
Write-Host 'Paperclip readiness tests passed.'
