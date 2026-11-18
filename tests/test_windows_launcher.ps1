# Offline Windows PowerShell 5.1 regression: powershell.exe -NoProfile -File tests/test_windows_launcher.ps1
# No Python, PyManager, npm, network, or changes to the machine's Python registrations required.
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$id = [guid]::NewGuid().ToString()
$fixture = Join-Path ([IO.Path]::GetTempPath()) "Paperclip launcher test $id"
$registry = "HKCU:\Software\PaperclipLauncherTest-$id"
$oldEnv = @{}
foreach ($name in 'Path','LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)','ProgramW6432','SystemDrive') {
    $oldEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    New-Item -ItemType Directory -Path $fixture | Out-Null
    $template = Join-Path $fixture 'shim.exe'
    Add-Type -OutputType ConsoleApplication -OutputAssembly $template -TypeDefinition @'
using System;
using System.IO;
class Shim {
    static int Main(string[] args) {
        string exe = typeof(Shim).Assembly.Location;
        File.AppendAllText(exe + ".calls", string.Join("|", args) + "\n");
        if (args.Length == 4 && args[0] == "-I" && args[1] == "-S" && args[2] == "-c" && args[3].Contains("sys.executable")) {
            if (!File.Exists(exe + ".json")) return 2;
            string json = File.ReadAllText(exe + ".json");
            Console.WriteLine(System.Text.RegularExpressions.Regex.Replace(json, @"[^\x00-\x7f]", m => @"\u" + ((int)m.Value[0]).ToString("x4")));
            return 0;
        }
        if (args.Length == 5 && File.Exists(args[0]) && args[1] == "--probe-paperclip" && args[3] == "--probe-timeout") {
            Console.WriteLine("ok");
            return 0;
        }
        return args.Length == 1 && File.Exists(args[0]) && Path.GetFileName(args[0]) == "app.py" ? 0 : 3;
    }
}
'@
    function New-TestPython([string]$Dir, [int[]]$Version, [string]$Reports, [string]$Name = 'python.exe') {
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        $exe = Join-Path $Dir $Name
        Copy-Item -LiteralPath $template -Destination $exe
        if (-not $Reports) { $Reports = $exe }
        [IO.File]::WriteAllText("$exe.json", (@{executable=$Reports; version=$Version} | ConvertTo-Json -Compress))
        return $exe
    }

    # Isolate PATH and the ordinary fallback directories from any real installations.
    $env:LOCALAPPDATA = Join-Path $fixture 'User Data'
    $env:ProgramFiles = Join-Path $fixture 'Program Files'
    ${env:ProgramFiles(x86)} = $env:ProgramFiles
    $env:ProgramW6432 = $env:ProgramFiles
    $env:SystemDrive = $fixture
    $real314 = New-TestPython "$fixture\Real Python 314" (3,14,4)
    $front314 = New-TestPython "$fixture\Python on PATH" (3,14,4) $real314
    $old = New-TestPython "$fixture\Old on PATH" (3,9,19)
    $fallback315 = New-TestPython "$env:LOCALAPPDATA\Programs\Python\Python315" (3,15,0)
    $registered = New-TestPython "$fixture\Registered off PATH" (3,15,1)
    $store = New-TestPython "$env:LOCALAPPDATA\Microsoft\WindowsApps" (3,99,0)
    $manager = New-TestPython "$env:ProgramFiles\PyManager" (3,99,0) -Name 'py.exe'
    $env:Path = ((@($store,$manager,$old,$front314) | ForEach-Object { Split-Path $_ -Parent }) -join ';')

    # A private PEP 514 tree: try both the default install directory and ExecutablePath.
    $key = "$registry\PythonCore\3.15\InstallPath"
    New-Item -Path $key -Value (Split-Path $registered -Parent) -Force | Out-Null
    . (Join-Path $project 'scripts/windows-python.ps1')
    $readRegistry = ${function:Get-RegisteredPythonPaths}
    & {
        function Get-RegisteredPythonPaths { & $readRegistry -Roots $registry }
        if ((Resolve-DashboardPython).Executable -ne $registered) { throw 'Missed a newer, off-PATH registry install' }
        New-ItemProperty -LiteralPath $key -Name ExecutablePath -Value $registered -PropertyType String | Out-Null
        Set-Item -LiteralPath $key -Value "$fixture\Missing directory"
        if ((Resolve-DashboardPython).Executable -ne $registered) { throw 'Ignored the PEP 514 ExecutablePath' }
        Remove-ItemProperty -LiteralPath $key -Name ExecutablePath
        if ((Resolve-DashboardPython).Executable -ne $fallback315) { throw 'Missed the per-user Python315 directory' }
        $selected = Resolve-DashboardPython -PythonVersion '3.14'
        if ($selected.Executable -ne $real314 -or $selected.Version -ne [version]'3.14.4') { throw 'Did not use sys.executable for the requested minor' }
        if ((Resolve-DashboardPython -PythonExe $real314).Executable -ne $real314) { throw 'Ignored an explicit path' }
        foreach ($invalid in @(@{PythonExe=$old}, @{PythonExe=$manager}, @{PythonExe=$store},
                              @{PythonExe="$fixture\missing.exe"}, @{PythonExe=$real314;PythonVersion='3.15'})) {
            $failed = $false
            try { $null = Resolve-DashboardPython @invalid } catch { $failed = $_.Exception.Message -like 'No working Python*' }
            if (-not $failed) { throw 'Accepted an invalid explicit interpreter or silently fell back' }
        }
    }
    if ((Test-Path "$store.calls") -or (Test-Path "$manager.calls")) { throw 'Invoked a Store alias or py.exe' }

    # Entry-point integration: same real executable probes Paperclip and starts dashboard/app.py.
    $setup = Join-Path $fixture 'setup-dashboard.ps1'
    Copy-Item (Join-Path $project 'setup-dashboard.ps1') $setup
    Copy-Item (Join-Path $project 'scripts') $fixture -Recurse
    $dashboard = Join-Path $fixture 'dashboard'
    New-Item -ItemType Directory -Path $dashboard | Out-Null
    $appFile = Join-Path $dashboard 'app.py'
    [IO.File]::WriteAllText($appFile, '')
    [IO.File]::WriteAllText("$dashboard\.env.example", "# keep this comment`r`n")
    & $setup -PythonExe $front314 -PythonVersion '3.14' -PaperclipUrl 'http://localhost:3200' -NoBrowser
    if ($LASTEXITCODE -ne 0) { throw 'Setup failed with an explicit interpreter' }
    $calls = [IO.File]::ReadAllLines("$real314.calls")
    if ($calls -notcontains "$appFile|--probe-paperclip|http://localhost:3200|--probe-timeout|5" -or $calls[-1] -ne $appFile) {
        throw 'Wrong executable, URL or arguments for readiness/dashboard launch'
    }
    $saved = [IO.File]::ReadAllLines("$dashboard\.env")
    if ($saved -notcontains '# keep this comment' -or $saved -notcontains 'PAPERCLIP_API_URL=http://localhost:3200') { throw 'Lost .env settings' }
    Write-Host 'Windows interpreter discovery and launch tests passed.'
} finally {
    foreach ($name in $oldEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process') }
    if (Test-Path -LiteralPath $registry) { Remove-Item -LiteralPath $registry -Recurse -Force }
    if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
}
exit 0
