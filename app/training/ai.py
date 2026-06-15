from __future__ import annotations

import json
import re
from typing import Any


TRAINING_SYSTEM_PROMPT = """
你是 Nexa AI API 平台的知识训练 Agent。

你的任务是把操作者提供的占星、命理或咨询资料整理成可检索、可审核、可复用的知识片段。

你必须：
- 只抽取资料中已经提供的观点，不补充外部知识。
- 把散文资料整理成客户咨询时可用的解释规则。
- 保留适用条件和禁用边界。
- 避免宿命论、恐吓、医疗、法律、投资或确定性预测。
- 输出结构化 JSON，不输出 Markdown、解释文字或代码块。
""".strip()

TRAINING_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "domain": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "rule_type": {"type": "string"},
                    "use_when": {"type": "string"},
                    "avoid_when": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["title", "body", "domain", "tags", "rule_type", "use_when", "avoid_when", "examples", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["chunks"],
    "additionalProperties": False,
}


def compact_training_text(text: str, limit: int = 900) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip("，。；、 ") + "..."


def build_training_prompt(source_title: str, entries: list[dict], max_entries: int = 6) -> str:
    lines = [
        f"资料名称：{source_title}",
        f"本批次条目数：{min(len(entries), max_entries)}",
        "",
        "请把下面资料整理成知识片段。每个片段应该能独立被检索并用于客户咨询回答。",
        "输出要求：最多输出 6 个 chunks；每个 body 控制在 120-260 个中文字符；examples 最多 2 条。",
        "标题清楚，正文可直接作为解读依据，tags 适合检索，confidence 表示抽取准确度。",
        "",
        "资料条目：",
    ]
    for index, entry in enumerate(entries[:max_entries], start=1):
        lines.extend(
            [
                f"{index}. {entry.get('title') or source_title}",
                f"source_id: {entry.get('source_id') or ''}",
                f"chunk_id: {entry.get('chunk_id') or ''}",
                f"tags: {', '.join(entry.get('tags') or [])}",
                f"body: {compact_training_text(entry.get('body') or entry.get('content') or '')}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def strip_json_fence(text: str) -> str:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        clean = "\n".join(lines).strip()
    return clean


def extract_json_candidate(text: str) -> str:
    clean = strip_json_fence(text)
    if clean.startswith(("{", "[")):
        return clean

    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(clean):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(clean[index:])
        except json.JSONDecodeError:
            continue
        return clean[index : index + end].strip()
    return clean


def parse_training_response(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_candidate(text))
    except json.JSONDecodeError as exc:
        raise ValueError("模型输出不是有效 JSON") from exc

    if isinstance(parsed, list):
        return {"chunks": parsed}
    if not isinstance(parsed, dict):
        raise ValueError("模型输出 JSON 必须是对象或片段数组")
    if not isinstance(parsed.get("chunks"), list):
        raise ValueError("模型输出缺少 chunks 数组")
    return parsed


def clean_tag(value: Any) -> str:
    return " ".join(str(value or "").split())


def unique_tags(values: list[Any]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = clean_tag(value)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def normalize_training_chunk(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(raw.get("title") or "").split())
    body = str(raw.get("body") or "").strip()
    if not title or not body:
        return None

    body_parts = [body]
    use_when = str(raw.get("use_when") or "").strip()
    avoid_when = str(raw.get("avoid_when") or "").strip()
    examples = [str(item).strip() for item in raw.get("examples") or [] if str(item).strip()]
    if use_when:
        body_parts.append(f"适用：{use_when}")
    if avoid_when:
        body_parts.append(f"边界：{avoid_when}")
    if examples:
        body_parts.append("例句：" + "；".join(examples[:2]))

    raw_tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    tags = unique_tags(["ai_training", raw.get("domain") or "astrology", *raw_tags, raw.get("rule_type")])
    return {
        "title": title,
        "content": "\n".join(body_parts),
        "domain": str(raw.get("domain") or "astrology"),
        "tags": tags,
        "confidence": float(raw.get("confidence") or 0),
        "status": "draft",
    }


def normalize_training_chunks(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = []
    for raw_chunk in parsed.get("chunks") or []:
        if not isinstance(raw_chunk, dict):
            continue
        chunk = normalize_training_chunk(raw_chunk)
        if chunk is not None:
            chunks.append(chunk)
    return chunks
