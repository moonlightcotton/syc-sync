$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'syc-sync.lnk'
if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Host "Startup shortcut removed: $lnkPath"
} else {
    Write-Host "Startup shortcut was not installed."
}

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -like '*watch.py*' -and $_.CommandLine -like "*$root*") {
        Stop-Process -Id $_.ProcessId -Force
        Write-Host "Stopped watcher process $($_.ProcessId)."
    }
}
Write-Host "Auto sync uninstalled."
