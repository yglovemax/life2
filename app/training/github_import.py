from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

from app.training.documents import SUPPORTED_TRAINING_EXTENSIONS


MAX_GITHUB_IMPORT_FILES = 30
MAX_GITHUB_FILE_BYTES = 5 * 1024 * 1024

JsonFetcher = Callable[[str], Any]
BytesFetcher = Callable[[str], bytes]


class GitHubImportError(ValueError):
    pass


@dataclass(frozen=True)
class GitHubTarget:
    owner: str
    repo: str
    ref: str
    path: str
    mode: str
    download_url: str = ""


@dataclass(frozen=True)
class GitHubFileRef:
    owner: str
    repo: str
    ref: str
    path: str
    download_url: str
    size: int = 0


def parse_github_url(url: str) -> GitHubTarget:
    clean_url = str(url or "").strip()
    parsed = urlparse(clean_url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise GitHubImportError("GitHub raw 链接格式不完整。")
        owner, repo, ref = parts[:3]
        return GitHubTarget(owner=owner, repo=repo, ref=ref, path="/".join(parts[3:]), mode="file", download_url=clean_url)

    if host not in {"github.com", "www.github.com"}:
        raise GitHubImportError("只支持公开 GitHub 链接。")
    if len(parts) < 2:
        raise GitHubImportError("GitHub 链接缺少 owner/repo。")

    owner, repo = parts[:2]
    if len(parts) == 2:
        return GitHubTarget(owner=owner, repo=repo, ref="", path="", mode="repo")

    marker = parts[2]
    if marker not in {"blob", "tree"} or len(parts) < 4:
        raise GitHubImportError("请使用 GitHub 仓库、文件或文件夹链接。")

    ref = parts[3]
    path = "/".join(parts[4:])
    if marker == "blob" and not path:
        raise GitHubImportError("GitHub 文件链接缺少路径。")
    return GitHubTarget(owner=owner, repo=repo, ref=ref, path=path, mode="file" if marker == "blob" else "dir")


def github_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Nexa-AI-API-Admin",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GitHubImportError(f"GitHub 读取失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GitHubImportError(f"GitHub 网络错误：{exc.reason}") from exc


def github_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Nexa-AI-API-Admin"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(MAX_GITHUB_FILE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise GitHubImportError(f"GitHub 文件下载失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GitHubImportError(f"GitHub 网络错误：{exc.reason}") from exc


def is_supported_github_file(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_TRAINING_EXTENSIONS


def github_contents_url(target: GitHubTarget, path: str, ref: str) -> str:
    quoted_path = quote(path.strip("/"), safe="/")
    suffix = f"/{quoted_path}" if quoted_path else ""
    return f"https://api.github.com/repos/{target.owner}/{target.repo}/contents{suffix}?ref={quote(ref, safe='')}"


def resolve_github_ref(target: GitHubTarget, json_fetcher: JsonFetcher) -> str:
    if target.ref:
        return target.ref
    data = json_fetcher(f"https://api.github.com/repos/{target.owner}/{target.repo}")
    ref = str(data.get("default_branch") or "").strip() if isinstance(data, dict) else ""
    if not ref:
        raise GitHubImportError("无法识别 GitHub 仓库默认分支。")
    return ref


def file_ref_from_item(target: GitHubTarget, ref: str, item: dict[str, Any]) -> GitHubFileRef | None:
    path = str(item.get("path") or item.get("name") or "").strip()
    download_url = str(item.get("download_url") or "").strip()
    if not path or not download_url or not is_supported_github_file(path):
        return None
    size = int(item.get("size") or 0)
    if size > MAX_GITHUB_FILE_BYTES:
        return None
    return GitHubFileRef(owner=target.owner, repo=target.repo, ref=ref, path=path, download_url=download_url, size=size)


def discover_github_files(
    target: GitHubTarget,
    json_fetcher: JsonFetcher = github_json,
    max_files: int = MAX_GITHUB_IMPORT_FILES,
) -> list[GitHubFileRef]:
    ref = resolve_github_ref(target, json_fetcher)
    if target.download_url:
        return [
            GitHubFileRef(target.owner, target.repo, ref, target.path, target.download_url)
        ] if is_supported_github_file(target.path) else []

    queue = [target.path] if target.path else [""]
    files: list[GitHubFileRef] = []
    while queue and len(files) < max_files:
        current_path = queue.pop(0)
        data = json_fetcher(github_contents_url(target, current_path, ref))
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "dir":
                queue.append(str(item.get("path") or ""))
                continue
            if item_type != "file":
                continue
            file_ref = file_ref_from_item(target, ref, item)
            if file_ref:
                files.append(file_ref)
                if len(files) >= max_files:
                    break

    if not files:
        raise GitHubImportError("没有找到可导入的训练资料文件。")
    return files


def github_upload_filename(file_ref: GitHubFileRef) -> str:
    safe_path = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "-", file_ref.path).strip("-")
    return f"{file_ref.owner}-{file_ref.repo}-{safe_path or Path(file_ref.path).name}"


def fetch_github_training_files(
    url: str,
    json_fetcher: JsonFetcher = github_json,
    bytes_fetcher: BytesFetcher = github_bytes,
    max_files: int = MAX_GITHUB_IMPORT_FILES,
) -> list[dict[str, Any]]:
    target = parse_github_url(url)
    file_refs = discover_github_files(target, json_fetcher=json_fetcher, max_files=max_files)
    files: list[dict[str, Any]] = []
    for file_ref in file_refs:
        content = bytes_fetcher(file_ref.download_url)
        if len(content) > MAX_GITHUB_FILE_BYTES:
            continue
        filename = github_upload_filename(file_ref)
        files.append(
            {
                "filename": filename,
                "content_type": mimetypes.guess_type(filename)[0] or "text/plain",
                "content": content,
                "metadata": {
                    "connector": "github",
                    "github_owner": file_ref.owner,
                    "github_repo": file_ref.repo,
                    "github_ref": file_ref.ref,
                    "github_path": file_ref.path,
                    "github_url": file_ref.download_url,
                },
            }
        )
    if not files:
        raise GitHubImportError("GitHub 文件为空或超过大小限制。")
    return files
