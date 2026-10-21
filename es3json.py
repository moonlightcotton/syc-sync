"""Read/write the Easy Save 3 (ES3) JSON dialect used by Chill With You.

ES3 serialises Dictionary<ulong, T> as ``{123:{...}}`` -- object keys are raw
numbers, not quoted strings, so the files are not strict JSON.  This module
implements a small tolerant parser plus a writer that reproduces the same
dialect.  Only the subset of JSON that ES3 emits is supported (objects,
arrays, strings, numbers, booleans, null).
"""
from __future__ import annotations

import json
import re

_RAW_KEY_RE = re.compile(r"-?\d+\Z")
# ES3 writes the keys of Dictionary<TKey, TValue> fields as raw tokens, while
# normal object property names are quoted.  These are the dictionary fields we
# know about in the save files we touch.
RAW_DICT_NAMES = {"TodoDic", "CompleteTodoListDic", "DiaryList", "Titles"}


class ParseError(ValueError):
    pass


def loads(text: str):
    parser = _Parser(text)
    value = parser.parse_value()
    parser.skip_ws()
    if not parser.at_end():
        raise ParseError(f"trailing data at offset {parser.i}")
    return value


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.i = 0
        self.n = len(text)

    def at_end(self) -> bool:
        return self.i >= self.n

    def skip_ws(self) -> None:
        while self.i < self.n and self.text[self.i] in " \t\r\n":
            self.i += 1

    def peek(self) -> str:
        if self.i >= self.n:
            raise ParseError("unexpected end of input")
        return self.text[self.i]

    def expect(self, ch: str) -> None:
        self.skip_ws()
        if self.peek() != ch:
            raise ParseError(f"expected {ch!r} at offset {self.i}, got {self.peek()!r}")
        self.i += 1

    def parse_value(self):
        self.skip_ws()
        c = self.peek()
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c == '"':
            return self.parse_string()
        if self.text.startswith("true", self.i):
            self.i += 4
            return True
        if self.text.startswith("false", self.i):
            self.i += 5
            return False
        if self.text.startswith("null", self.i):
            self.i += 4
            return None
        return self.parse_number()

    def parse_object(self) -> dict:
        self.expect("{")
        result = {}
        self.skip_ws()
        if self.peek() == "}":
            self.i += 1
            return result
        while True:
            self.skip_ws()
            if self.peek() == '"':
                key = self.parse_string()
            else:
                key = self.parse_raw_key()
            self.expect(":")
            result[key] = self.parse_value()
            self.skip_ws()
            c = self.peek()
            if c == ",":
                self.i += 1
                continue
            if c == "}":
                self.i += 1
                return result
            raise ParseError(f"expected ',' or '}}' at offset {self.i}, got {c!r}")

    def parse_raw_key(self) -> str:
        start = self.i
        while self.i < self.n and self.text[self.i] not in " \t\r\n:":
            self.i += 1
        key = self.text[start:self.i].strip()
        if not key:
            raise ParseError(f"empty object key at offset {start}")
        return key

    def parse_array(self) -> list:
        self.expect("[")
        result = []
        self.skip_ws()
        if self.peek() == "]":
            self.i += 1
            return result
        while True:
            result.append(self.parse_value())
            self.skip_ws()
            c = self.peek()
            if c == ",":
                self.i += 1
                continue
            if c == "]":
                self.i += 1
                return result
            raise ParseError(f"expected ',' or ']' at offset {self.i}, got {c!r}")

    def parse_string(self) -> str:
        start = self.i
        self.i += 1
        escaped = False
        while self.i < self.n:
            c = self.text[self.i]
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                self.i += 1
                token = self.text[start:self.i]
                return json.loads(token)
            self.i += 1
        raise ParseError("unterminated string")

    def parse_number(self):
        start = self.i
        while self.i < self.n and self.text[self.i] in "+-0123456789.eE":
            self.i += 1
        token = self.text[start:self.i]
        if not token:
            raise ParseError(f"unexpected character {self.peek()!r} at offset {self.i}")
        try:
            if any(ch in token for ch in ".eE"):
                return float(token)
            return int(token)
        except ValueError:
            raise ParseError(f"invalid number {token!r} at offset {start}") from None


def dumps(value, indent: int = 0, pretty: bool = True) -> str:
    out = []
    _write(value, out, indent, pretty)
    return "".join(out)


def _write(value, out, level: int, pretty: bool, raw_keys: bool = False) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(repr(value))
    elif isinstance(value, dict):
        if not value:
            out.append("{}")
            return
        out.append("{")
        first = True
        for key, item in value.items():
            if not first:
                out.append(",")
            first = False
            if pretty:
                out.append("\n" + "\t" * (level + 1))
            key_text = str(key)
            if raw_keys and _RAW_KEY_RE.match(key_text):
                out.append(key_text)
            else:
                out.append(json.dumps(key_text, ensure_ascii=False))
            out.append(":")
            child_raw = isinstance(item, dict) and key_text in RAW_DICT_NAMES
            _write(item, out, level + 1, pretty, raw_keys=child_raw)
        if pretty:
            out.append("\n" + "\t" * level)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        if not value:
            out.append("[]")
            return
        out.append("[")
        for idx, item in enumerate(value):
            if idx:
                out.append(",")
            if pretty:
                out.append("\n" + "\t" * (level + 1))
            _write(item, out, level + 1, pretty)
        if pretty:
            out.append("\n" + "\t" * level)
        out.append("]")
    else:
        raise TypeError(f"cannot serialise {type(value)!r}")


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        data = loads(text)
        again = loads(dumps(data))
        print(path, "roundtrip", data == again, "keys", list(data)[:3])
