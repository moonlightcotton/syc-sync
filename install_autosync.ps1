$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root 'runtime\pythonw.exe'
$watch = Join-Path $root 'watch.py'

if (-not (Test-Path $pythonw)) {
    Write-Host "[ERROR] runtime\pythonw.exe not found."
    exit 1
}
if (-not (Test-Path $watch)) {
    Write-Host "[ERROR] watch.py not found."
    exit 1
}

$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'syc-sync.lnk'
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($lnkPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $watch + '"'
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = 'syc sync - XJTU LMS to Chill With You'
$shortcut.Save()
Write-Host "Startup shortcut created: $lnkPath"

# Stop an older watcher of this same folder, then start a fresh one.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -like '*watch.py*' -and $_.CommandLine -like "*$root*") {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Start-Process -FilePath $pythonw -ArgumentList ('-B "' + $watch + '"') -WorkingDirectory $root -WindowStyle Hidden
Write-Host "syc sync watcher started."
Write-Host "It will refresh LMS periodically and apply tasks when the game is closed."
