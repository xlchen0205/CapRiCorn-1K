from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", flags=re.S | re.I)


def extract_json_from_text(text: str) -> Any | None:
    content = text.strip()

    match = JSON_BLOCK_RE.search(content)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    starts = [i for i in (content.find("{"), content.find("[")) if i != -1]
    ends = [i for i in (content.rfind("}"), content.rfind("]")) if i != -1]
    if starts and ends:
        start, end = min(starts), max(ends)
        if end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
    return rows


def derive_video_id(video_path: str) -> str:
    return Path(video_path).stem


def normalize_video_id(row: dict[str, Any]) -> dict[str, Any]:
    if "video_id" in row:
        video_id = str(row["video_id"])
    elif "video_path" in row:
        video_id = derive_video_id(str(row["video_path"]))
    else:
        raise KeyError("Expected row to contain video_id or video_path")

    normalized = dict(row)
    normalized["video_id"] = video_id
    normalized.pop("video_path", None)
    return normalized


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def duration_bin(duration: float) -> str | None:
    if 0 < duration <= 120:
        return "(0,120]"
    if 120 < duration <= 300:
        return "(120,300]"
    if 300 < duration <= 480:
        return "(300,480]"
    if 480 < duration <= 601:
        return "(480,601]"
    return None
