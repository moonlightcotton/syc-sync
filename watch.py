"""Background watcher: sync LMS todos when the game is not running.

Started at logon (see install_autosync.bat).  It does two things:
  * once an hour (and at startup) it refreshes the LMS cache with --auto;
  * as soon as the game process exits, it applies the cached tasks to the save,
    so the next launch has the current todo list.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = BASE_DIR
PYTHON = os.path.join(ROOT, "runtime", "python.exe")
SYNC = os.path.join(BASE_DIR, "sync.py")
LOG = os.path.join(ROOT, "logs", "watcher.log")
GAME_PROCESS = "Chill With You.exe"

sys.path.insert(0, BASE_DIR)


def load_config() -> dict:
    path = os.path.join(ROOT, "config.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


CONFIG = load_config()
try:
    FETCH_INTERVAL = max(30, int(CONFIG.get("fetch_interval_minutes", 120))) * 60
except Exception:
    FETCH_INTERVAL = 120 * 60
AUTO_MODE = str(CONFIG.get("auto_mode", "periodic"))


def log(message: str) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def already_running() -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\ChillWithYouLmsTodoWatcher")
    return kernel32.GetLastError() == 183


def game_running() -> bool:
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}", "/NH"],
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        ).decode("mbcs", "ignore")
        return GAME_PROCESS.lower() in out.lower()
    except Exception:
        return False


def run_sync(extra: list[str]) -> int:
    cmd = [PYTHON if os.path.isfile(PYTHON) else sys.executable, "-B", SYNC] + extra
    creationflags = 0x08000000 if os.name == "nt" else 0
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("\n$ " + " ".join(cmd) + "\n")
            f.flush()
            proc = subprocess.run(cmd, stdout=f, stderr=f, creationflags=creationflags,
                                  startupinfo=startupinfo,
                                  cwd=ROOT, timeout=900)
        return proc.returncode
    except Exception as exc:
        log(f"同步命令失败: {exc}")
        return 1


def main() -> int:
    if already_running():
        return 0
    log("watcher 启动")
    previous_running = game_running()
    last_fetch = 0.0
    while True:
        try:
            running = game_running()
            just_exited = previous_running and not running
            if just_exited:
                log("检测到游戏退出，应用缓存的待办…")
                time.sleep(5)
                run_sync(["--apply-only"])
                if AUTO_MODE == "on_exit":
                    log("按 on_exit 模式刷新 LMS 待办…")
                    last_fetch = time.time()
                    code = run_sync(["--auto"])
                    if code == 2:
                        log("LMS 登录已失效，等待下次手动登录。")
            if not running and AUTO_MODE != "on_exit":
                now = time.time()
                if now - last_fetch >= FETCH_INTERVAL:
                    last_fetch = now
                    log("定时刷新 LMS 待办…")
                    code = run_sync(["--auto"])
                    if code == 2:
                        log("LMS 登录已失效，等待下次手动登录。")
            previous_running = running
        except Exception as exc:
            log(f"watcher 循环异常: {exc}")
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
