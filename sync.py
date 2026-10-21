"""Chill With You x XJTU LMS todo sync.

Run with:
    python sync.py            # sync and write the game save (may open Edge to log in)
    python sync.py --auto     # unattended: skip if not logged in, never opens a login window
    python sync.py --dry-run  # only fetch/print, do not touch the save
    python sync.py --apply-only [--dry-run]  # use the last cached tasks
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import game_save
import tasks as task_builder
from driver_setup import ensure_driver
from lms_client import WebDriver, WebDriverError, fetch_lms_data

DEFAULT_CONFIG = {
    "target_list_title": "待办事项列表",
    "fallback_to_first_list": True,
    "include_types": ["homework", "exam"],
    "include_description": True,
    "description_max_chars": 500,
    "title_prefix": "",
    "include_locked": True,
    "remove_stale": True,
    "edge_binary": "",
    "driver_path": "",
    "profile_dir": "browser-profile",
    "game_process": "Chill With You.exe",
    "headless_auto": True,
    "note_enabled": True,
    "note_title": "LMS 作业",
    "note_page_first": True,
    "note_description_max_chars": 2000,
}

GAME_PROCESS = "Chill With You.exe"


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
        path = os.path.join(BASE_DIR, "logs",
                            "sync-" + datetime.now().strftime("%Y%m%d") + ".log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def acquire_single_instance():
    """Return a mutex handle, or None when another sync is already running."""
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ChillWithYouLmsTodoSync")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    path = os.path.join(BASE_DIR, "config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                config.update(json.load(f))
        except Exception as exc:
            log(f"config.json 读取失败，使用默认配置: {exc}")
    return config


def resolve(base_dir: str, value: str, default: str) -> str:
    value = value or default
    if not os.path.isabs(value):
        value = os.path.join(base_dir, value)
    return value


def game_running(process_name: str = GAME_PROCESS) -> bool:
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/NH"],
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        ).decode("mbcs", "ignore")
        return process_name.lower() in out.lower()
    except Exception:
        return False


def find_driver(config: dict) -> str:
    path = config.get("driver_path") or ""
    if path:
        path = resolve(BASE_DIR, path, "")
        if os.path.isfile(path):
            return path
    return ensure_driver(
        os.path.join(BASE_DIR, "tools"),
        config.get("edge_binary") or None,
        log,
    )


def read_last_tasks() -> list[dict]:
    path = os.path.join(BASE_DIR, "data", "lms_todos.json")
    if not os.path.isfile(path):
        raise RuntimeError("没有上次同步的缓存，请先运行一次同步。")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("tasks") or []
    return data


def write_cache(lms_data: dict, built: list[dict], config: dict) -> None:
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    payload = {
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "https://lms.xjtu.edu.cn/api/todos",
        "count": len(built),
        "tasks": built,
        "raw_todos": lms_data.get("todos", []),
    }
    with open(os.path.join(data_dir, "lms_todos.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    lines = [f"同步时间: {payload['synced_at']}", f"共 {len(built)} 项", ""]
    for idx, task in enumerate(built, 1):
        lines.append(f"{idx}. {task.get('note_line') or task['text']}")
        lines.append("")
    with open(os.path.join(data_dir, "lms_todos.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_state() -> dict:
    path = os.path.join(BASE_DIR, "data", "state.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"managed": {}}


def save_state(state: dict) -> None:
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "state.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_note_state() -> dict:
    path = os.path.join(BASE_DIR, "data", "note_state.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"saves": {}}


def save_note_state(state: dict) -> None:
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "note_state.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def apply_to_game(built: list[dict], config: dict, dry_run: bool = False) -> int:
    if game_running(config.get("game_process") or GAME_PROCESS):
        log("游戏正在运行，跳过写入存档。请关闭游戏后再次运行，或运行 --apply-only。")
        return 3
    save_dirs = game_save.find_save_dirs()
    if not save_dirs:
        log("没有找到游戏存档目录，请先启动一次游戏。")
        return 1
    errors = []
    note_state_all = load_note_state()
    for save_dir in save_dirs:
        todo = None
        try:
            todo = game_save.pick_todo_list(
                save_dir, config.get("target_list_title"),
                fallback=bool(config.get("fallback_to_first_list", True)),
            )
        except game_save.SaveError as exc:
            errors.append(str(exc))
        if todo is not None:
            target_title = config.get("target_list_title")
            if target_title and todo.get("title") != target_title:
                log(f"未找到标题为“{target_title}”的待办列表，改用「{todo.get('title')}」。")
            log(f"找到待办列表「{todo.get('title')}」: {todo['path']}")
            before = len(todo["value"].get("TodoDic") or {})
            state = load_state()
            report = game_save.merge_tasks(
                todo, built, state,
                remove_stale=bool(config.get("remove_stale", True)),
            )
            if dry_run:
                log(f"待办试运行：原有 {before} 项，新增 {report['added']}，"
                    f"更新 {report['updated']}，移除 {report['removed']}，"
                    f"合并后 {report['total']} 项（未写入文件）。")
            else:
                backup = game_save.backup_file(todo["path"],
                                               os.path.join(BASE_DIR, "backups"))
                game_save.save_todo(todo)
                save_state(state)
                log(f"已写入待办：新增 {report['added']}，更新 {report['updated']}，"
                    f"移除 {report['removed']}，当前共 {report['total']} 项。")
                log(f"备份：{backup}")

        if config.get("note_enabled", True):
            note_state = note_state_all.setdefault("saves", {}).setdefault(save_dir, {})
            nreport = game_save.merge_notes(
                save_dir, built, note_state, config,
                dry_run=dry_run,
                backup_dir=os.path.join(BASE_DIR, "backups"),
            )
            log(f"笔记：新增 {nreport['added']} 行，累计 {nreport['lines']} 行，"
                f"已屏蔽 {nreport['suppressed']} 条"
                + ("（页面已重建）" if nreport["page_created"] else "")
                + ("（页面已被删除）" if nreport["page_deleted"] else "")
                + ("（试运行，未写入）" if dry_run else "。"))
            if not dry_run:
                save_note_state(note_state_all)

        if todo is not None:
            return 0
    log("写入失败：" + ("；".join(errors) if errors else "未知错误"))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="syc sync: 西交 LMS 待办 → Chill With You")
    parser.add_argument("--auto", action="store_true",
                        help="无人值守模式；若未登录 LMS 则直接退出，不弹出登录窗口")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写存档")
    parser.add_argument("--apply-only", action="store_true",
                        help="使用上次缓存的待办，不访问 LMS")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    mutex = acquire_single_instance()
    if mutex is None:
        log("另一个同步任务正在运行，跳过本次。")
        return 0

    config = load_config()

    if args.apply_only:
        try:
            built = read_last_tasks()
        except Exception as exc:
            log(str(exc))
            return 1
        return apply_to_game(built, config, dry_run=args.dry_run)

    driver_path = find_driver(config)
    profile_dir = resolve(BASE_DIR, config.get("profile_dir") or "browser-profile",
                          "browser-profile")
    headless = bool(config.get("headless_auto", True)) if args.auto else False
    driver = None
    try:
        log("启动 Edge…")
        driver = WebDriver(driver_path, profile_dir, headless=headless,
                           edge_binary=config.get("edge_binary") or None)
        driver.get("https://lms.xjtu.edu.cn/user/index#/#%2F")
        time.sleep(2)
        if not args.auto:
            log("如果 Edge 中显示登录页，请完成登录（最多等待 10 分钟）…")
        if not driver.wait_for_login(timeout=8 if args.auto else 600,
                                     on_wait=(None if args.auto else lambda url: None)):
            if args.auto:
                log("LMS 登录已失效，自动模式跳过。请手动运行一次完成登录。")
                return 2
            log("等待登录超时。请重新运行并在 Edge 窗口中登录。")
            return 2
        log("已登录 LMS。")
        lms_data = fetch_lms_data(driver)
        log(f"/api/todos 返回 {len(lms_data['todos'])} 项。")
        built = task_builder.build_tasks(lms_data, config)
        write_cache(lms_data, built, config)
        log(f"已生成 {len(built)} 条游戏待办（缓存 data/lms_todos.json）。")
        if args.dry_run:
            for idx, task in enumerate(built, 1):
                print(f"\n--- {idx} ---\n{task['text']}")
            return apply_to_game(built, config, dry_run=True)
        return apply_to_game(built, config, dry_run=False)
    except WebDriverError as exc:
        log(f"浏览器/LMS 错误: {exc}")
        return 1
    except Exception as exc:
        log(f"同步失败: {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    sys.exit(main())
