"""Turn XJTU LMS todo data into Chill With You todo entries."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser

CST = timezone(timedelta(hours=8))

TYPE_LABELS = {
    "homework": "作业",
    "exam": "测验",
    "questionnaire": "问卷",
    "discussion": "讨论",
    "material": "资料",
}

_BLOCK_TAGS = {
    "br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "blockquote", "pre",
}


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    parser = _HTMLText()
    try:
        parser.feed(html)
        parser.close()
        text = unescape("".join(parser.parts))
    except Exception:
        text = re.sub(r"<[^>]+>", " ", unescape(html))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST)


def stable_game_id(key: str) -> int:
    digest = hashlib.sha256(("chill-lms:" + key).encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return value or 1


def _shorten(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _short_course(name: str) -> str:
    name = re.sub(r"（[^）]*）|\([^)]*\)", "", name or "").strip()
    for sep in ("：", ":"):
        if sep in name:
            name = name.split(sep)[-1].strip()
    name = re.sub(r"\s+", "", name)
    return _shorten(name, 8)


def _clean_course(name: str) -> str:
    """Drop semester/parenthetical noise such as （2026-2027学年第一学期）."""
    name = re.sub(r"（[^）]*）|\([^)]*\)", "", name or "").strip()
    return re.sub(r"\s+", " ", name)


def build_tasks(lms_data: dict, config: dict) -> list[dict]:
    todos = lms_data.get("todos", [])
    details = lms_data.get("details", {})
    include_types = set(config.get("include_types") or ["homework", "exam"])
    max_chars = int(config.get("description_max_chars", 500))
    prefix = config.get("title_prefix", "")
    include_desc = bool(config.get("include_description", True))
    include_locked = bool(config.get("include_locked", True))

    tasks: list[dict] = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if include_types and kind not in include_types:
            continue
        if item.get("is_locked") and not include_locked:
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        key = f"{kind}:{item_id}"
        title = str(item.get("title") or "").strip() or "(无标题)"
        course = str(item.get("course_name") or "").strip()
        deadline = parse_iso_utc(item.get("end_time"))
        locked = bool(item.get("is_locked"))

        detail = details.get(f"/api/activities/{item_id}") or details.get(f"/api/exams/{item_id}") or {}
        description = ""
        if include_desc and not locked:
            if kind == "homework":
                data = detail.get("data") if isinstance(detail.get("data"), dict) else {}
                description = html_to_text(data.get("description"))
            elif kind == "exam":
                description = html_to_text(detail.get("description"))

        display_title = title + ("（测验）" if kind == "exam" else "")
        # The todo cell is a small two-line input field.  Keep only a short
        # title there; the full description goes to the note page.
        todo_text = _shorten(display_title, 14)
        text = todo_text

        expire = deadline.strftime("%Y%m%d%H%M%S") if deadline else ""
        deadline_text = deadline.strftime("%Y-%m-%d %H:%M") if deadline else "未设置"
        note_max = int(config.get("note_description_max_chars", 2000))
        note_desc = description.replace("\n", " ").strip() if description else ""
        if not note_desc:
            note_desc = "LMS 尚未解锁" if locked else "无说明"
        note_desc = note_desc.rstrip("。．.，,；; ")
        note_desc = _shorten(note_desc, note_max)
        note_title = title
        note_course = _clean_course(course) or "未知课程"
        note_line = (f"《{note_course}》{note_title}：{note_desc}"
                     f"，截止时间：{deadline_text}")
        url = ""
        if item.get("course_id"):
            if kind == "exam":
                url = (f"https://lms.xjtu.edu.cn/course/{item['course_id']}"
                       f"/learning-activity#/exam/{item_id}")
            else:
                url = (f"https://lms.xjtu.edu.cn/course/{item['course_id']}"
                       f"/learning-activity#/{item_id}")
        tasks.append({
            "key": key,
            "type": kind,
            "id": item_id,
            "title": title,
            "course": course,
            "course_id": item.get("course_id"),
            "deadline": deadline.isoformat() if deadline else None,
            "deadline_text": deadline_text,
            "expire": expire,
            "text": text,
            "note_line": note_line,
            "description": description,
            "locked": locked,
            "game_id": stable_game_id(key),
            "url": url,
        })

    tasks.sort(key=lambda t: (t["deadline"] or "9999", t["course"], t["title"]))
    return tasks
