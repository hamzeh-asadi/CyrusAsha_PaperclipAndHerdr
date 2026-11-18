# Run with Windows PowerShell 5.1: powershell.exe -NoProfile -File tests/test_windows_launcher.ps1
# Exercise the actual Get-Command/PATH and native argument handling. No npm, Python or live service needed.
$ErrorActionPreference = 'Stop'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ("Paperclip launcher test " + [guid]::NewGuid())
$oldPath = $env:Path

# The setup script only needs a ready health response for this test.
function Invoke-RestMethod { @{ status = 'ok' } }

try {
    $first = Join-Path $fixture 'Program Files'
    $second = Join-Path $fixture 'Other launchers'
    $dashboard = Join-Path $fixture 'dashboard'
    New-Item -ItemType Directory -Path $first, $second, $dashboard -Force | Out-Null
    $setup = Join-Path $fixture 'setup-dashboard.ps1'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../setup-dashboard.ps1') -Destination $setup
    [IO.File]::WriteAllText((Join-Path $dashboard '.env.example'), '')

    $firstPy = Join-Path $first 'py.exe'
    $secondPy = Join-Path $second 'py.exe'
    $direct = Join-Path $first 'python.exe'
    Add-Type -OutputType ConsoleApplication -OutputAssembly $firstPy -TypeDefinition @'
using System;
using System.IO;
class Shim {
    static int Main(string[] args) {
        string exe = typeof(Shim).Assembly.Location;
        bool launcher = Path.GetFileName(exe) == "py.exe";
        if (args.Length == 0 || (args[0] == "-3") != launcher) return 2;
        if (Array.IndexOf(args, "-c") >= 0) {
            Console.WriteLine(File.Exists(exe + ".ready") ? "1" : "0");
            return 0;
        }
        File.WriteAllText(exe + ".args", string.Join("|", args));
        return 0;
    }
}
'@
    Copy-Item -LiteralPath $firstPy -Destination $secondPy
    Copy-Item -LiteralPath $firstPy -Destination $direct
    $env:Path = "$first;$second;$([Environment]::SystemDirectory)"

    foreach ($exe in $secondPy, $direct) {
        # First py.exe never works. Try the next py.exe, then test fallback to python.exe.
        [IO.File]::WriteAllText("$exe.ready", '')
        & $setup -PaperclipUrl 'http://localhost:3100' -NoBrowser
        if ($LASTEXITCODE -ne 0) { throw "Setup failed to select $exe" }
        $expected = if ($exe -eq $direct) { 'dashboard/app.py' } else { '-3|dashboard/app.py' }
        if ([IO.File]::ReadAllText("$exe.args") -ne $expected) { throw "Wrong dashboard arguments for $exe" }
        Remove-Item -LiteralPath "$exe.ready"
    }
    & $setup -PaperclipUrl 'http://localhost:3100' -NoBrowser *> $null
    if ($LASTEXITCODE -ne 1) { throw 'Setup accepted a launcher without a compatible interpreter' }
    Write-Host 'Windows Python discovery tests passed.'
} finally {
    $env:Path = $oldPath
    if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
}
exit 0
