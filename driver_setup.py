"""Keep msedgedriver.exe in sync with the installed Edge major version."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

from lms_client import find_edge

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)\.(\d+)")


def _version_tuple(text: str):
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(x) for x in match.groups())


def edge_version(edge_binary: str | None = None) -> tuple[int, ...] | None:
    edge_binary = edge_binary or find_edge()
    base = os.path.dirname(edge_binary)
    versions = []
    try:
        for name in os.listdir(base):
            if os.path.isdir(os.path.join(base, name)):
                ver = _version_tuple(name)
                if ver and name == ".".join(map(str, ver)):
                    versions.append(ver)
    except OSError:
        pass
    return max(versions) if versions else None


def driver_version(driver_path: str) -> tuple[int, ...] | None:
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000
        out = subprocess.check_output(
            [driver_path, "--version"],
            stderr=subprocess.STDOUT,
            timeout=15,
            startupinfo=startupinfo,
            creationflags=creationflags,
        ).decode("utf-8", "replace")
        return _version_tuple(out)
    except Exception:
        return None


def _download_driver(version: tuple[int, ...], tools_dir: str, log) -> str | None:
    version_text = ".".join(map(str, version))
    url = f"https://msedgedriver.microsoft.com/{version_text}/edgedriver_win64.zip"
    log(f"下载匹配的 Edge WebDriver {version_text}…")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "driver.zip")
            with open(archive, "wb") as f:
                f.write(data)
            with zipfile.ZipFile(archive) as zf:
                member = next((n for n in zf.namelist()
                               if n.lower().endswith("msedgedriver.exe")), None)
                if not member:
                    raise RuntimeError("压缩包中没有 msedgedriver.exe")
                target = os.path.join(tools_dir, "msedgedriver.exe")
                with zf.open(member) as src, open(target + ".new", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.replace(target + ".new", target)
        return os.path.join(tools_dir, "msedgedriver.exe")
    except Exception as exc:
        log(f"WebDriver 下载失败: {exc}")
        return None


def ensure_driver(tools_dir: str, edge_binary: str | None, log) -> str:
    """Return a usable msedgedriver path, downloading it when necessary."""
    os.makedirs(tools_dir, exist_ok=True)
    path = os.path.join(tools_dir, "msedgedriver.exe")
    edge_ver = edge_version(edge_binary)
    drv_ver = driver_version(path) if os.path.isfile(path) else None

    if edge_ver is None:
        if os.path.isfile(path):
            return path
        raise RuntimeError("找不到 Microsoft Edge，无法确定 WebDriver 版本。")

    if drv_ver is not None and drv_ver[:1] == edge_ver[:1]:
        return path

    downloaded = _download_driver(edge_ver, tools_dir, log)
    if downloaded:
        return downloaded
    if os.path.isfile(path):
        log(f"警告：WebDriver {drv_ver} 与 Edge {edge_ver} 版本不一致，尝试继续。")
        return path
    raise RuntimeError("缺少 msedgedriver.exe，且自动下载失败。")
