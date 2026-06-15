from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_TRAINING_EXTENSIONS = {".docx", ".pdf", ".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class TrainingEntry:
    title: str
    body: str
    source_file: str
    source_hash: str
    placement_type: str
    target: str


def safe_upload_filename(filename: str) -> str:
    name = Path(str(filename or "")).name.strip()
    if not name:
        return "upload.txt"
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", name)
    return name or "upload.txt"


def source_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(text: str) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip()).strip()


def split_plain_text(text: str, source_title: str, limit: int = 1800) -> list[tuple[str, str]]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [clean_text(block) for block in re.split(r"\n\s*\n+", normalized) if clean_text(block)]
    if not blocks and text.strip():
        blocks = [clean_text(text)]

    chunks: list[tuple[str, str]] = []
    for block in blocks:
        if len(block) <= limit:
            chunks.append((f"{source_title} #{len(chunks) + 1}", block))
            continue
        for start in range(0, len(block), limit):
            chunks.append((f"{source_title} #{len(chunks) + 1}", block[start : start + limit]))
    return chunks


def split_markdown(text: str, fallback_title: str) -> list[tuple[str, str]]:
    current_title = fallback_title
    current_lines: list[str] = []
    chunks: list[tuple[str, str]] = []

    def flush() -> None:
        body = clean_text("\n".join(current_lines))
        if body:
            chunks.append((current_title, body))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading:
            flush()
            current_title = heading.group(1).strip() or fallback_title
            current_lines = []
            continue
        current_lines.append(raw_line)
    flush()
    return chunks or split_plain_text(text, fallback_title)


def entries_from_chunks(chunks: list[tuple[str, str]], path: Path, placement_type: str) -> list[TrainingEntry]:
    file_hash = source_hash(path)
    entries: list[TrainingEntry] = []
    for title, body in chunks:
        clean_body = clean_text(body)
        if not clean_body:
            continue
        entries.append(
            TrainingEntry(
                title=title.strip() or path.stem,
                body=clean_body,
                source_file=path.name,
                source_hash=file_hash,
                placement_type=placement_type,
                target=path.suffix.lower().lstrip("."),
            )
        )
    return entries


def parse_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("DOCX 文件结构不完整，无法解析。") from exc

    root = ET.fromstring(document_xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def parse_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - optional dependency path.
        raise ValueError("PDF 解析需要安装 pypdf。") from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(page for page in pages if page.strip())


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def parse_training_document(path: str | Path) -> list[TrainingEntry]:
    doc_path = Path(path)
    suffix = doc_path.suffix.lower()
    if suffix not in SUPPORTED_TRAINING_EXTENSIONS:
        raise ValueError(f"暂不支持 {suffix or '无扩展名'} 文件。")
    if not doc_path.exists():
        raise ValueError(f"找不到训练资料：{doc_path}")

    if suffix == ".docx":
        text = parse_docx_text(doc_path)
        return entries_from_chunks(split_plain_text(text, doc_path.stem), doc_path, "uploaded_docx")
    if suffix == ".pdf":
        text = parse_pdf_text(doc_path)
        return entries_from_chunks(split_plain_text(text, doc_path.stem), doc_path, "uploaded_pdf")
    if suffix in {".md", ".markdown"}:
        text = read_text_file(doc_path)
        return entries_from_chunks(split_markdown(text, doc_path.stem), doc_path, "uploaded_markdown")

    text = read_text_file(doc_path)
    return entries_from_chunks(split_plain_text(text, doc_path.stem), doc_path, "uploaded_text")


def entries_to_markdown(entries: list[TrainingEntry]) -> str:
    sections: list[str] = []
    for entry in entries:
        sections.append(f"# {entry.title}\n{entry.body}")
    return "\n\n".join(sections)
