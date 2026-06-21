#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from math import comb
from pathlib import Path
from typing import Any, Iterable

from eval_utils import (
    duration_bin,
    extract_json_from_text,
    normalize_video_id,
    read_jsonl,
)
from judge_client import JudgeConfig, call_with_transport_retries
from prompts import CATEGORIZE_TEMPLATE


def is_valid_response(model_generation: Any, subject_captions: list[str]) -> bool:
    if not isinstance(model_generation, dict):
        return False
    collected: list[str] = []
    for subject_list in model_generation.values():
        if not isinstance(subject_list, list):
            return False
        collected.extend(subject_list)

    if len(collected) != len(subject_captions):
        if len(subject_captions) < 10:
            return False
        if 10 <= len(subject_captions) < 20 and abs(
            len(collected) - len(subject_captions)
        ) > 1:
            return False
        if 20 <= len(subject_captions) < 30 and abs(
            len(collected) - len(subject_captions)
        ) > 2:
            return False
        if 30 <= len(subject_captions) and abs(
            len(collected) - len(subject_captions)
        ) > 3:
            return False

    return set(collected) == set(subject_captions)


def process_video(
    stage1_row: dict[str, Any],
    caption: str,
    config: JudgeConfig,
    response_retries: int,
    transport_retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "video_id": stage1_row["video_id"],
        "categorization_info": {},
    }
    caption_subjects: dict[str, list[str]] = {}
    for subject_id, event_judgements in stage1_row["main_sbj_info"].items():
        caption_subjects[subject_id] = []
        for item in event_judgements:
            if item["judgement"] in {
                "correctly mentioned",
                "mentioned but with errors",
            }:
                caption_subjects[subject_id].append(
                    item["subject_description_in_caption"]
                )

    for subject_id, subject_captions in caption_subjects.items():
        info: dict[str, Any] = {"sbj_captions": subject_captions}
        if len(subject_captions) > 1:
            prompt = CATEGORIZE_TEMPLATE.format(subject_captions, caption)
            messages = [{"role": "user", "content": prompt}]
            judgement = None
            for _ in range(response_retries):
                completion = call_with_transport_retries(
                    messages,
                    config,
                    retries=transport_retries,
                    retry_delay=retry_delay,
                )
                if completion is None:
                    continue
                candidate = extract_json_from_text(completion)
                if is_valid_response(candidate, subject_captions):
                    judgement = candidate
                    break
            info["gpt_categorization"] = (
                judgement if judgement is not None else "Judge Failed"
            )
        else:
            info["gpt_categorization"] = None
        output["categorization_info"][subject_id] = info
    return output


def referential_consistency(counts: Iterable[int], total_events: int) -> float:
    if total_events <= 1:
        raise ValueError("total_events must be greater than 1")
    numerator = sum(comb(count, 2) for count in counts if count >= 2)
    return numerator / comb(total_events, 2)


def calculate_metrics(
    categorization_rows: list[dict[str, Any]],
    stage1_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    stage1_map = {row["video_id"]: row for row in stage1_rows}
    sample_referential_consistency: list[float] = []
    bins = {
        name: []
        for name in ("(0,120]", "(120,300]", "(300,480]", "(480,601]")
    }
    per_video: list[dict[str, Any]] = []

    for data in categorization_rows:
        metadata = stage1_map[data["video_id"]]
        subject_event_counts = {
            subject_id: len(items)
            for subject_id, items in metadata["main_sbj_info"].items()
        }
        weighted_sum = 0.0
        total_weight = 0
        subject_scores: dict[str, float] = {}

        for subject_id, info in data["categorization_info"].items():
            total_events = subject_event_counts[subject_id]
            if total_events <= 1:
                continue
            categorization = info["gpt_categorization"]
            if categorization == "Judge Failed":
                continue
            if categorization is None:
                score = 0.0
            else:
                counts = [len(items) for items in categorization.values()]
                score = referential_consistency(counts, total_events)
            weighted_sum += score
            total_weight += 1
            subject_scores[subject_id] = score

        if total_weight == 0:
            continue
        video_score = weighted_sum / total_weight
        sample_referential_consistency.append(video_score)
        bucket = duration_bin(metadata["duration"])
        if bucket:
            bins[bucket].append(video_score)
        per_video.append(
            {
                "video_id": data["video_id"],
                "duration": metadata["duration"],
                "referential_consistency": video_score,
                "subject_referential_consistency": subject_scores,
            }
        )

    duration_metrics = {
        name: {
            "count": len(values),
            "referential_consistency": sum(values) / len(values),
        }
        for name, values in bins.items()
        if values
    }
    return {
        "referential_consistency": (
            sum(sample_referential_consistency)
            / len(sample_referential_consistency)
        ),
        "count": len(sample_referential_consistency),
        "duration_bins": duration_metrics,
        "per_video": per_video,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--stage1-results", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key")
    parser.add_argument("--model", required=True)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--response-retries", type=int, default=5)
    parser.add_argument("--transport-retries", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-tokens", type=int, default=3072)
    parser.add_argument("--temperature", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "2_judge_referential_consistency.jsonl"
    metrics_path = output_dir / "2_referential_consistency_metrics.json"

    predictions = {
        row["video_id"]: row
        for row in (normalize_video_id(row) for row in read_jsonl(args.predictions))
    }
    stage1_rows = [normalize_video_id(row) for row in read_jsonl(args.stage1_results)]
    existing = (
        {normalize_video_id(row)["video_id"] for row in read_jsonl(output_path)}
        if output_path.exists()
        else set()
    )
    config = JudgeConfig.from_args(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    tasks = [row for row in stage1_rows if row["video_id"] not in existing]
    with output_path.open("a", encoding="utf-8") as output:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_video,
                    row,
                    predictions[row["video_id"]]["caption"],
                    config,
                    args.response_retries,
                    args.transport_retries,
                    args.retry_delay,
                ): row["video_id"]
                for row in tasks
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    output.write(json.dumps(result, ensure_ascii=False) + "\n")
                    output.flush()
                except Exception:
                    print(f"Failed video: {futures[future]}")
                    traceback.print_exc()

    metrics = calculate_metrics(
        [normalize_video_id(row) for row in read_jsonl(output_path)],
        stage1_rows,
    )
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Overall Referential Consistency: "
        f"{metrics['referential_consistency']:.3f}"
    )


if __name__ == "__main__":
    main()
