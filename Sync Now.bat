@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    echo [ERROR] runtime\python.exe not found. Please keep the folder intact.
    pause
    exit /b 1
)
echo syc sync: Syncing XJTU LMS todos into Chill With You...
echo If this is the first run, an Edge window will open. Please log in there.
"runtime\python.exe" -B "sync.py" %*
echo.
pause
