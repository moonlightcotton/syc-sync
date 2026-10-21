"""Minimal Edge WebDriver client + XJTU LMS API access.

Only the Python standard library is used, so this works with the embeddable
Python runtime shipped next to it.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

LMS_HOME = "https://lms.xjtu.edu.cn/user/index#/#%2F"
LMS_ORIGIN = "https://lms.xjtu.edu.cn"

DEFAULT_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class WebDriverError(RuntimeError):
    pass


def find_edge() -> str:
    for path in DEFAULT_EDGE_PATHS:
        if os.path.isfile(path):
            return path
    raise WebDriverError("找不到 Microsoft Edge，请确认已安装 Edge 浏览器。")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebDriver:
    def __init__(self, driver_path: str, profile_dir: str, headless: bool = True,
                 edge_binary: str | None = None, timeout: int = 120):
        self.driver_path = driver_path
        self.profile_dir = profile_dir
        self.headless = headless
        self.edge_binary = edge_binary or find_edge()
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        os.makedirs(profile_dir, exist_ok=True)
        creationflags = 0x08000000 if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        self.proc = subprocess.Popen(
            [driver_path, f"--port={self.port}", "--silent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        self._wait_ready()
        args = [
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-extensions",
        ]
        if headless:
            args.append("--headless=new")
            args.append("--window-size=1280,900")
        else:
            args.append("--start-maximized")
        caps = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "msedge",
                    "ms:edgeOptions": {"binary": self.edge_binary, "args": args},
                }
            }
        }
        res = self._call("POST", "/session", caps, timeout=timeout)
        self.session_id = res["value"]["sessionId"]
        self.path = f"/session/{self.session_id}"
        self._call("POST", self.path + "/timeouts",
                   {"script": 180000, "pageLoad": 120000, "implicit": 0})

    def _wait_ready(self) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.base + "/status", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise WebDriverError("msedgedriver 启动失败")

    def _call(self, method: str, path: str, payload=None, timeout: int = 120):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise WebDriverError(f"WebDriver HTTP {e.code}: {body}") from None
        except urllib.error.URLError as e:
            raise WebDriverError(f"WebDriver 连接失败: {e}") from None

    def get(self, url: str) -> None:
        self._call("POST", self.path + "/url", {"url": url})

    def current_url(self) -> str:
        return self._call("GET", self.path + "/url")["value"]

    def execute(self, script: str, *args, timeout: int = 120):
        value = self._call("POST", self.path + "/execute/sync",
                           {"script": script, "args": list(args)}, timeout=timeout)["value"]
        return value

    def execute_async(self, script: str, *args, timeout: int = 180):
        value = self._call("POST", self.path + "/execute/async",
                           {"script": script, "args": list(args)}, timeout=timeout)["value"]
        return value

    def is_logged_in(self) -> bool:
        try:
            return bool(self.execute(
                "return typeof window.globalData !== 'undefined' && !!window.globalData && "
                "!!window.globalData.user"
            ))
        except WebDriverError:
            return False

    def wait_for_login(self, on_wait=None, timeout: int = 600) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                url = self.current_url()
            except WebDriverError:
                time.sleep(2)
                continue
            if "lms.xjtu.edu.cn" in url:
                try:
                    if self.is_logged_in():
                        return True
                except WebDriverError:
                    pass
            if on_wait:
                on_wait(url)
            time.sleep(2)
        return False

    def fetch_text(self, url: str) -> tuple[int, str]:
        script = r"""
            const done = arguments[arguments.length - 1];
            const url = arguments[0];
            function b64(s) {
              const bytes = new TextEncoder().encode(s);
              let bin = '';
              const chunk = 0x8000;
              for (let i = 0; i < bytes.length; i += chunk) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
              }
              return btoa(bin);
            }
            fetch(url, {credentials: 'include'})
              .then(r => r.text().then(t => done(JSON.stringify({status: r.status, b64: b64(t)}))))
              .catch(e => done(JSON.stringify({status: -1, error: String(e)})));
        """
        raw = self.execute_async(script, url)
        obj = json.loads(raw)
        if obj.get("status") == -1:
            raise WebDriverError(f"请求 {url} 失败: {obj.get('error')}")
        return int(obj["status"]), base64.b64decode(obj["b64"]).decode("utf-8")

    def fetch_many(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        script = r"""
            const done = arguments[arguments.length - 1];
            const urls = arguments[0];
            function b64(s) {
              const bytes = new TextEncoder().encode(s);
              let bin = '';
              const chunk = 0x8000;
              for (let i = 0; i < bytes.length; i += chunk) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
              }
              return btoa(bin);
            }
            Promise.all(urls.map(u => fetch(u, {credentials: 'include'})
              .then(r => r.text().then(t => [u, r.status, b64(t)]))
              .catch(e => [u, -1, String(e)])))
              .then(pairs => {
                const out = {};
                for (const [u, s, t] of pairs) out[u] = [s, t];
                done(JSON.stringify(out));
              });
        """
        raw = self.execute_async(script, urls, timeout=180)
        obj = json.loads(raw)
        result = {}
        for url, (status, b64_or_err) in obj.items():
            if status == -1:
                result[url] = (-1, b64_or_err)
            else:
                result[url] = (int(status), base64.b64decode(b64_or_err).decode("utf-8"))
        return result

    def quit(self) -> None:
        try:
            self._call("DELETE", self.path, timeout=10)
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            pass


def fetch_lms_data(driver: WebDriver) -> dict:
    """Fetch /api/todos and the detail of every item that exposes one."""
    status, body = driver.fetch_text("/api/todos")
    if status != 200:
        raise WebDriverError(f"/api/todos 返回 HTTP {status}: {body[:300]}")
    todos = json.loads(body).get("todo_list", [])
    if not isinstance(todos, list):
        raise WebDriverError("/api/todos 返回格式异常")

    detail_urls = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        item_id = item.get("id")
        if not item_id:
            continue
        if kind == "homework" and not item.get("is_locked"):
            detail_urls.append(f"/api/activities/{item_id}")
        elif kind == "exam":
            detail_urls.append(f"/api/exams/{item_id}")

    details: dict[str, dict] = {}
    if detail_urls:
        fetched = driver.fetch_many(detail_urls)
        for url, (code, text) in fetched.items():
            if code == 200:
                try:
                    details[url] = json.loads(text)
                except json.JSONDecodeError:
                    pass

    return {"todos": todos, "details": details}
