# Locate installed interpreters, not py.exe launchers. Dot-sourced by setup-dashboard.ps1.
function Get-RegisteredPythonPaths([string[]]$Roots = @(
    'HKCU:\Software\Python', 'HKLM:\Software\Python',
    'HKLM:\Software\WOW6432Node\Python', 'HKCU:\Software\WOW6432Node\Python'
)) {
    # PEP 514: Company\Tag\InstallPath can supply ExecutablePath or just a default directory.
    foreach ($root in $Roots) {
        foreach ($key in (Get-Item -Path "$root\*\*\InstallPath" -ErrorAction SilentlyContinue)) {
            $exe = $key.GetValue('ExecutablePath')
            if ($exe) { $exe }
            $dir = $key.GetValue('')
            if ($dir) { [IO.Path]::Combine($dir, 'python.exe') }
        }
    }
}

function Get-InstalledPythonPaths {
    foreach ($cmd in (Get-Command -Name 'python.exe','python3.exe' -CommandType Application -All -ErrorAction SilentlyContinue)) {
        $cmd.Path
    }
    Get-RegisteredPythonPaths
    # Some installs survive launcher removal without a PATH entry or registration.
    # Inspect only immediate Python* installation directories, not entire drives.
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)
    if ($env:LOCALAPPDATA) { $roots += "$env:LOCALAPPDATA\Programs\Python", "$env:LOCALAPPDATA\Python" }
    if ($env:SystemDrive) { $roots += "$env:SystemDrive\" }
    foreach ($root in ($roots | Where-Object { $_ } | Select-Object -Unique)) {
        foreach ($dir in (Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
            [IO.Path]::Combine($dir.FullName, 'python.exe')
        }
    }
}

# Apply the same exclusions to each candidate and to the path reported by sys.executable.
function Get-InterpreterFile([string]$Path) {
    $file = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($file -isnot [IO.FileInfo] -or $file.Extension -ne '.exe' -or
        $file.Name -in 'py.exe','pyw.exe','pythonw.exe' -or $file.FullName -like '*\PyManager\*') { return }
    if ($env:LOCALAPPDATA -and $file.FullName.StartsWith("$env:LOCALAPPDATA\Microsoft\WindowsApps\", [StringComparison]::OrdinalIgnoreCase)) { return }
    return $file
}

function Resolve-DashboardPython([string]$PythonExe, [string]$PythonVersion) {
    $paths = if ($PythonExe) { $PythonExe } else { Get-InstalledPythonPaths }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $best = $null
    foreach ($path in $paths) {
        $file = Get-InterpreterFile $path
        if (-not $file -or -not $seen.Add($file.FullName)) { continue }
        try {
            $exe = $file.FullName
            # ASCII JSON handles spaces and non-ASCII paths even on legacy Windows code pages.
            $raw = & $exe -I -S -c 'import json,sys; print(json.dumps(dict(executable=sys.executable,version=sys.version_info[:3])))' 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $raw) { continue }
            $info = $raw | ConvertFrom-Json -ErrorAction Stop
            $version = [version]($info.version -join '.')
            if ($version.Major -ne 3 -or $version.Minor -lt 10) { continue }
            if ($PythonVersion -and $version.ToString(2) -ne $PythonVersion) { continue }
            $real = [string]$info.executable
            if (-not [IO.Path]::IsPathRooted($real)) { continue }
            $interpreter = Get-InterpreterFile $real
            if (-not $interpreter) { continue }
            if (-not $best -or $version -gt $best.Version) {
                $best = [pscustomobject]@{ Executable = $interpreter.FullName; Version = $version }
            }
        } catch { Write-Verbose "Skipping ${path}: $($_.Exception.Message)" }
    }
    if (-not $best) {
        $wanted = if ($PythonVersion) { $PythonVersion } else { '3.10+' }
        $where = if ($PythonExe) { " at '$PythonExe'" } else { '' }
        throw "No working Python $wanted interpreter$where. Use -PythonExe with the full path to the installed python.exe. PyManager is not required."
    }
    return $best
}
