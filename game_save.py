"""Read/merge/write the game's TodoListData save file."""
from __future__ import annotations

import glob
import gzip
import json
import os
import shutil
import time
from datetime import datetime, timezone

import es3json

TODO_TYPE_MARKER = "Bulbul.TodoListData"
NOTE_LIST_MARKER = "Bulbul.NoteList"
PAGE_DATA_MARKER = "Bulbul.PageDataV2"
NOTE_LIST_KEY = "-1678955942"
PAGE_DATA_KEY = "-195136877"
DEFAULT_PAGE_TITLES = {"新页面", "New Page", "Untitled", ""}
SAVE_SUBDIR = os.path.join("AppData", "LocalLow", "nestopi", "Chill With You",
                           "SaveData", "Release", "v2")


class SaveError(RuntimeError):
    pass


def find_save_dirs() -> list[str]:
    base = os.path.join(os.environ.get("USERPROFILE", ""), SAVE_SUBDIR)
    dirs = []
    if os.path.isdir(base):
        for name in os.listdir(base):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                dirs.append(path)
    return dirs


def read_gzip_json(path: str) -> str:
    with gzip.open(path, "rb") as f:
        return f.read().decode("utf-8")


def write_gzip_json(path: str, text: str) -> None:
    tmp = path + ".lmsmod.tmp"
    data = text.encode("utf-8")
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            gz.write(data)
    os.replace(tmp, path)


def find_todo_lists(save_dir: str) -> list[dict]:
    result = []
    for path in glob.glob(os.path.join(save_dir, "*.es3")):
        try:
            text = read_gzip_json(path)
        except Exception:
            continue
        if TODO_TYPE_MARKER not in text:
            continue
        try:
            root = es3json.loads(text)
        except Exception:
            continue
        for key, wrapper in root.items():
            if not isinstance(wrapper, dict) or TODO_TYPE_MARKER not in str(wrapper.get("__type", "")):
                continue
            value = wrapper.get("value")
            if not isinstance(value, dict):
                continue
            result.append({
                "path": path,
                "root": root,
                "root_key": key,
                "value": value,
                "title": value.get("TitleText"),
            })
    return result


def pick_todo_list(save_dir: str, title: str | None = None,
                   fallback: bool = True) -> dict:
    lists = find_todo_lists(save_dir)
    if not lists:
        raise SaveError("没有找到游戏待办列表存档。请先启动一次游戏并打开“待办”功能。")
    if title:
        for item in lists:
            if item.get("title") == title:
                return item
        if not fallback:
            raise SaveError(f"没有找到标题为“{title}”的待办列表。可用列表："
                            + "、".join(repr(x.get("title")) for x in lists))
    return lists[0]


def _as_int(value) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value).strip())


def merge_tasks(todo: dict, tasks: list[dict], state: dict,
                remove_stale: bool = True) -> dict:
    """Merge generated tasks into the selected TodoListData in-place.

    Returns a small report dict.
    """
    value = todo["value"]
    todo_dic = value.setdefault("TodoDic", {})
    order = value.setdefault("TodoOrderList", [])
    if not isinstance(todo_dic, dict):
        raise SaveError("TodoDic 结构异常")
    if not isinstance(order, list):
        order = []
        value["TodoOrderList"] = order

    managed = state.setdefault("managed", {})
    current_ids = set()
    added = updated = skipped = 0

    for task in tasks:
        uid = int(task["game_id"])
        uid_str = str(uid)
        current_ids.add(uid_str)
        text = task["text"]
        expire = task.get("expire", "")

        existing = todo_dic.get(uid_str)
        if isinstance(existing, dict):
            existing["TodoText"] = text
            existing["expireDateTimeString"] = expire
            existing.setdefault("CurrentState", 0)
            existing.setdefault("completeDateTimeString", "")
            existing.setdefault("UniqueID", uid)
            updated += 1
        else:
            todo_dic[uid_str] = {
                "UniqueID": uid,
                "TodoText": text,
                "CurrentState": 0,
                "completeDateTimeString": "",
                "expireDateTimeString": expire,
            }
            order.append(uid)
            added += 1

        managed[uid_str] = {
            "key": task.get("key"),
            "type": task.get("type"),
            "title": task.get("title"),
            "course": task.get("course"),
        }

    removed = 0
    if remove_stale:
        for uid_str in list(managed.keys()):
            if uid_str in current_ids:
                continue
            entry = todo_dic.get(uid_str)
            try:
                is_complete = int(entry.get("CurrentState", 0)) == 1 if isinstance(entry, dict) else False
            except Exception:
                is_complete = False
            if isinstance(entry, dict) and not is_complete:
                del todo_dic[uid_str]
                order[:] = [x for x in order if _as_int(x) != int(uid_str)]
                removed += 1
            managed.pop(uid_str, None)

    # Keep IDs in TodoOrderList unique and present.
    seen = set()
    cleaned = []
    for item in order:
        try:
            value_int = _as_int(item)
        except Exception:
            continue
        if str(value_int) in todo_dic and value_int not in seen:
            seen.add(value_int)
            cleaned.append(value_int)
    # Append any task that somehow lost its order entry.
    for uid_str in todo_dic.keys():
        try:
            uid = int(uid_str)
        except Exception:
            continue
        if uid not in seen:
            cleaned.append(uid)
            seen.add(uid)
    value["TodoOrderList"] = cleaned

    state["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {"added": added, "updated": updated, "removed": removed,
            "total": len(todo_dic)}


def backup_file(path: str, backup_dir: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    target = os.path.join(backup_dir, os.path.basename(path) + f".{stamp}.bak")
    shutil.copy2(path, target)
    # Keep the backup directory small; the save file itself is tiny.
    prefix = os.path.basename(path) + "."
    backups = sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir)
         if name.startswith(prefix) and name.endswith(".bak")),
        key=os.path.getmtime,
    )
    for old in backups[:-50]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target


def save_todo(todo: dict) -> None:
    text = es3json.dumps(todo["root"], pretty=True)
    write_gzip_json(todo["path"], text)


# ---------------------------------------------------------------------------
# Notes (NoteList + PageDataV2)
# ---------------------------------------------------------------------------

def find_note_list(save_dir: str) -> dict | None:
    for path in glob.glob(os.path.join(save_dir, "*.es3")):
        try:
            text = read_gzip_json(path)
        except Exception:
            continue
        if NOTE_LIST_MARKER not in text:
            continue
        try:
            root = es3json.loads(text)
        except Exception:
            continue
        for key, wrapper in root.items():
            if not isinstance(wrapper, dict):
                continue
            if NOTE_LIST_MARKER not in str(wrapper.get("__type", "")):
                continue
            value = wrapper.get("value")
            if not isinstance(value, dict):
                continue
            return {
                "path": path,
                "root": root,
                "root_key": key,
                "value": value,
            }
    return None


def note_page_path(save_dir: str, page_id: int) -> str:
    return os.path.join(save_dir, f"{PAGE_DATA_KEY}_{page_id}.es3")


def load_note_page(save_dir: str, page_id: int) -> dict | None:
    path = note_page_path(save_dir, page_id)
    if not os.path.isfile(path):
        return None
    try:
        root = es3json.loads(read_gzip_json(path))
    except Exception:
        return None
    for key, wrapper in root.items():
        if isinstance(wrapper, dict) and PAGE_DATA_MARKER in str(wrapper.get("__type", "")):
            value = wrapper.get("value")
            if isinstance(value, dict):
                return {"path": path, "root": root, "root_key": key, "value": value}
    return None


def _new_note_list() -> dict:
    root = {
        NOTE_LIST_KEY: {
            "__type": "Bulbul.NoteList,Assembly-CSharp",
            "value": {"Titles": {}, "PageOrderList": []},
        }
    }
    return {
        "path": "",
        "root": root,
        "root_key": NOTE_LIST_KEY,
        "value": root[NOTE_LIST_KEY]["value"],
    }


def _new_page(page_id: int, text: str) -> dict:
    value = {"UniqueID": page_id, "ScrollValue": 0, "MainText": text}
    root = {
        PAGE_DATA_KEY: {
            "__type": "Bulbul.PageDataV2,Assembly-CSharp",
            "value": value,
        }
    }
    return {
        "path": "",
        "root": root,
        "root_key": PAGE_DATA_KEY,
        "value": value,
    }


def _new_page_id(note: dict) -> int:
    titles = note["value"].get("Titles") or {}
    now = datetime.now(timezone.utc)
    ticks = int((now - datetime(1, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10_000_000)
    while str(ticks) in titles:
        ticks += 1
    return ticks


def _find_page_by_title(note: dict, title: str) -> int | None:
    titles = note["value"].get("Titles") or {}
    for page_id, page_title in titles.items():
        if page_title == title:
            return int(page_id)
    return None


def _find_empty_default_page(note: dict, save_dir: str) -> tuple[int, dict] | None:
    """Find the game's freshly-created empty '新页面' page, if present."""
    titles = note["value"].get("Titles") or {}
    for page_id, page_title in titles.items():
        if page_title not in DEFAULT_PAGE_TITLES:
            continue
        page = load_note_page(save_dir, int(page_id))
        if page is not None and not (page["value"].get("MainText") or "").strip():
            return int(page_id), page
    return None


def merge_notes(save_dir: str, tasks: list[dict], state: dict,
                config: dict, dry_run: bool = False,
                backup_dir: str | None = None) -> dict:
    """Append LMS assignments to a dedicated note page.

    Existing note lines are left untouched.  If a line that this mod wrote is
    later removed (or edited) by the user, its task key is added to
    ``suppressed`` and will never be written again.
    """
    note = find_note_list(save_dir)
    first_run = not state
    page_id = state.get("page_id")
    lines = dict(state.get("lines") or {})
    suppressed = set(state.get("suppressed") or [])
    page_deleted = False
    page = None

    if page_id:
        page = load_note_page(save_dir, page_id)
        titles = (note or {}).get("value", {}).get("Titles", {})
        if page is None or str(page_id) not in titles:
            page_deleted = True
            page = None

    if page_deleted:
        for key in lines:
            suppressed.add(key)
        lines.clear()
        page_id = None

    note_title = str(config.get("note_title") or "LMS 作业")
    note_list_changed = False
    if page is None and first_run and note is not None:
        adopted = _find_page_by_title(note, note_title)
        if adopted is not None:
            candidate = load_note_page(save_dir, adopted)
            if candidate is not None:
                page = candidate
                page_id = adopted
        if page is None:
            empty_default = _find_empty_default_page(note, save_dir)
            if empty_default is not None:
                page_id, page = empty_default
                titles = note["value"].setdefault("Titles", {})
                titles[str(page_id)] = note_title
                note_list_changed = True

    if page is not None and note is not None and not state.get("default_pages_cleaned") \
            and config.get("remove_empty_default_pages", True):
        titles = note["value"].setdefault("Titles", {})
        order = note["value"].setdefault("PageOrderList", [])
        for pid_text, title_text in list(titles.items()):
            try:
                pid = int(pid_text)
            except Exception:
                continue
            if pid == int(page_id) or title_text not in DEFAULT_PAGE_TITLES:
                continue
            other = load_note_page(save_dir, pid)
            if other is None or (other["value"].get("MainText") or "").strip():
                continue
            del titles[pid_text]
            try:
                order[:] = [x for x in order if int(x) != pid]
            except Exception:
                pass
            try:
                os.remove(other["path"])
            except OSError:
                pass
            note_list_changed = True

    current_text = ""
    current_lines: list[str] = []
    if page is not None:
        current_text = page["value"].get("MainText") or ""
        current_lines = current_text.splitlines()

        # Detect lines deleted (or edited) by the user.
        for key, line in list(lines.items()):
            if line not in current_lines:
                suppressed.add(key)
                del lines[key]

        # On the first run, adopt lines that are already on the page.
        if first_run:
            for task in tasks:
                line = task.get("note_line")
                if line and line in current_lines and task["key"] not in lines:
                    lines[task["key"]] = line

    additions = []
    for task in tasks:
        key = task["key"]
        if key in suppressed or key in lines:
            continue
        line = task.get("note_line")
        if not line:
            continue
        additions.append((key, line))

    page_created = False
    if additions:
        if page is None:
            page_id = _new_page_id(note or _new_note_list())
            text = "\n".join(line for _, line in additions)
            page = _new_page(page_id, text)
            page_created = True
            if note is None:
                note = _new_note_list()
                note["path"] = os.path.join(save_dir, f"{NOTE_LIST_KEY}.es3")
            titles = note["value"].setdefault("Titles", {})
            titles[str(page_id)] = note_title
            order = note["value"].setdefault("PageOrderList", [])
            order.insert(0, page_id)
            note_list_changed = True
        else:
            text = current_text.rstrip("\n")
            if text:
                text += "\n"
            text += "\n".join(line for _, line in additions)
            page["value"]["MainText"] = text
            page_id = int(page["value"].get("UniqueID", page_id))
        for key, line in additions:
            lines[key] = line

    note_list_changed = note_list_changed or page_created
    if note is not None and page_id and config.get("note_page_first", True):
        order = note["value"].setdefault("PageOrderList", [])
        try:
            ids = [int(x) for x in order]
            index = ids.index(int(page_id))
            if index != 0:
                order.pop(index)
                order.insert(0, int(page_id))
                note_list_changed = True
        except ValueError:
            order.insert(0, int(page_id))
            note_list_changed = True

    result = {
        "page_created": page_created,
        "page_deleted": page_deleted,
        "added": len(additions),
        "suppressed": len(suppressed),
        "lines": len(lines),
        "page_id": page_id,
    }

    if dry_run:
        return result

    if page_created and note is not None:
        if not note.get("path"):
            note["path"] = os.path.join(save_dir, f"{NOTE_LIST_KEY}.es3")
        if page is not None and not page.get("path"):
            page["path"] = note_page_path(save_dir, int(page_id))
        if backup_dir and os.path.isfile(note["path"]):
            backup_file(note["path"], backup_dir)
        save_note_list(note)
        save_note_page(page)
    elif page is not None and additions:
        if backup_dir and os.path.isfile(page["path"]):
            backup_file(page["path"], backup_dir)
        save_note_page(page)
    if note_list_changed and not page_created and note is not None:
        if backup_dir and note.get("path") and os.path.isfile(note["path"]):
            backup_file(note["path"], backup_dir)
        save_note_list(note)

    state.clear()
    state.update({
        "page_id": page_id,
        "page_title": note_title,
        "lines": lines,
        "suppressed": sorted(suppressed),
        "default_pages_cleaned": True,
    })
    return result


def save_note_list(note: dict) -> None:
    if not note.get("path"):
        raise SaveError("NoteList 路径为空")
    write_gzip_json(note["path"], es3json.dumps(note["root"], pretty=True))


def save_note_page(page: dict) -> None:
    if not page.get("path"):
        raise SaveError("PageDataV2 路径为空")
    write_gzip_json(page["path"], es3json.dumps(page["root"], pretty=True))
