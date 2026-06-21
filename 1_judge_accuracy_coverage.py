#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from eval_utils import (
    duration_bin,
    extract_json_from_text,
    normalize_video_id,
    read_jsonl,
)
from judge_client import JudgeConfig, call_with_transport_retries
from prompts import OTHER_EVENT_TEMPLATE, SUBJECT_EVENT_TEMPLATE


EVENT_TYPES = {
    "correctly mentioned",
    "mentioned but with errors",
    "not mentioned",
}


def extract_subject_ids(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in re.finditer(r"<[^<>]+>", text):
        subject_id = match.group(0)
        if subject_id not in seen:
            seen.add(subject_id)
            result.append(subject_id)
    return result


def normalize_subject_keys(judgement: dict[str, Any]) -> None:
    descriptions = judgement["subject_description_in_caption"]
    judgement["subject_description_in_caption"] = {
        key if key.startswith("<") and key.endswith(">") else f"<{key}>": value
        for key, value in descriptions.items()
    }


def is_valid_response(
    model_generation: Any,
    query_type: str,
    subject_ids: list[str] | None,
) -> bool:
    if not isinstance(model_generation, dict):
        return False

    if query_type == "subject_events":
        if set(model_generation) != {
            "event_type",
            "reason",
            "subject_description_in_caption",
        }:
            return False
        if model_generation["event_type"] not in EVENT_TYPES:
            return False
        descriptions = model_generation["subject_description_in_caption"]
        if not isinstance(descriptions, dict):
            return False
        if (
            model_generation["event_type"] == "not mentioned"
            and set(descriptions.values()) != {None}
        ):
            return False
        if model_generation["event_type"] in {
            "correctly mentioned",
            "mentioned but with errors",
        }:
            if all(value is None for value in descriptions.values()):
                return False
            normalize_subject_keys(model_generation)
            if set(model_generation["subject_description_in_caption"]) != set(subject_ids or []):
                return False
        return True

    if query_type == "other_events":
        return (
            set(model_generation) == {"event_type", "reason"}
            and model_generation["event_type"] in EVENT_TYPES
        )
    raise ValueError(f"Unknown query type: {query_type}")


def judge_prompt(
    prompt: str,
    query_type: str,
    subject_ids: list[str] | None,
    config: JudgeConfig,
    response_retries: int,
    transport_retries: int,
    retry_delay: float,
) -> dict[str, Any] | None:
    messages = [{"role": "user", "content": prompt}]
    for _ in range(response_retries):
        completion = call_with_transport_retries(
            messages,
            config,
            retries=transport_retries,
            retry_delay=retry_delay,
        )
        if completion is None:
            continue
        judgement = extract_json_from_text(completion)
        if is_valid_response(judgement, query_type, subject_ids):
            return judgement
    return None


def process_video(
    prediction: dict[str, Any],
    annotation: dict[str, Any],
    config: JudgeConfig,
    response_retries: int,
    transport_retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    video_id = prediction["video_id"]
    caption = prediction["caption"]

    output: dict[str, Any] = {
        "video_id": video_id,
        "duration": annotation["duration"],
        "main_sbj_info": defaultdict(list),
        "other_event_judge": [],
    }
    events = annotation["events"]

    for event in events["main_sbj_evts"] + events["main_sbj_ints"]:
        subject_ids = extract_subject_ids(event)
        prompt = SUBJECT_EVENT_TEMPLATE.format(caption, event, subject_ids)
        judgement = judge_prompt(
            prompt,
            "subject_events",
            subject_ids,
            config,
            response_retries,
            transport_retries,
            retry_delay,
        )
        if judgement is None:
            for subject_id in subject_ids:
                output["main_sbj_info"][subject_id].append(
                    {
                        "event": event,
                        "judgement": "failed",
                        "reason": None,
                        "subject_description_in_caption": None,
                    }
                )
            continue

        normalize_subject_keys(judgement)
        for subject_id in subject_ids:
            output["main_sbj_info"][subject_id].append(
                {
                    "event": event,
                    "judgement": judgement["event_type"],
                    "reason": judgement["reason"],
                    "subject_description_in_caption": judgement[
                        "subject_description_in_caption"
                    ][subject_id],
                }
            )

    for event in events["bg_desc"] + events["trans_desc"] + events["minor_evts"]:
        prompt = OTHER_EVENT_TEMPLATE.format(caption, event)
        judgement = judge_prompt(
            prompt,
            "other_events",
            None,
            config,
            response_retries,
            transport_retries,
            retry_delay,
        )
        if judgement is None:
            output["other_event_judge"].append(
                {"event": event, "judgement": "failed", "reason": None}
            )
        else:
            output["other_event_judge"].append(
                {
                    "event": event,
                    "judgement": judgement["event_type"],
                    "reason": judgement["reason"],
                }
            )
    output["main_sbj_info"] = dict(output["main_sbj_info"])
    return output


def calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_accuracy: list[float] = []
    sample_coverage: list[float] = []
    bins = {
        name: {"accuracy": [], "coverage": []}
        for name in ("(0,120]", "(120,300]", "(300,480]", "(480,601]")
    }
    per_video: list[dict[str, Any]] = []

    for data in rows:
        event_list: list[str] = []
        correct = 0.0
        mentioned_with_errors = 0.0
        total = 0.0

        for event_judgements in data["main_sbj_info"].values():
            for item in event_judgements:
                if item["event"] in event_list:
                    continue
                event_list.append(item["event"])
                total += 1
                if item["judgement"] == "correctly mentioned":
                    correct += 1
                elif item["judgement"] == "mentioned but with errors":
                    mentioned_with_errors += 1

        for item in data["other_event_judge"]:
            assert item["event"] not in event_list
            event_list.append(item["event"])
            total += 1
            if item["judgement"] == "correctly mentioned":
                correct += 1
            elif item["judgement"] == "mentioned but with errors":
                mentioned_with_errors += 1

        accuracy = correct / total
        coverage = (correct + mentioned_with_errors) / total
        sample_accuracy.append(accuracy)
        sample_coverage.append(coverage)
        bucket = duration_bin(data["duration"])
        if bucket:
            bins[bucket]["accuracy"].append(accuracy)
            bins[bucket]["coverage"].append(coverage)
        per_video.append(
            {
                "video_id": data["video_id"],
                "duration": data["duration"],
                "accuracy": accuracy,
                "coverage": coverage,
            }
        )

    duration_metrics: dict[str, Any] = {}
    for name, values in bins.items():
        if values["accuracy"]:
            duration_metrics[name] = {
                "count": len(values["accuracy"]),
                "accuracy": sum(values["accuracy"]) / len(values["accuracy"]),
                "coverage": sum(values["coverage"]) / len(values["coverage"]),
            }

    return {
        "accuracy": sum(sample_accuracy) / len(sample_accuracy),
        "coverage": sum(sample_coverage) / len(sample_coverage),
        "count": len(rows),
        "duration_bins": duration_metrics,
        "per_video": per_video,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key")
    parser.add_argument("--model", required=True)
    parser.add_argument("--workers", type=int, default=20)
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
    judgements_path = output_dir / "1_judge_accuracy_coverage.jsonl"
    metrics_path = output_dir / "1_accuracy_coverage_metrics.json"

    annotations = {
        row["video_id"]: row
        for row in (normalize_video_id(row) for row in read_jsonl(args.annotations))
    }
    predictions = [normalize_video_id(row) for row in read_jsonl(args.predictions)]
    existing = (
        {normalize_video_id(row)["video_id"] for row in read_jsonl(judgements_path)}
        if judgements_path.exists()
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

    tasks = [row for row in predictions if row["video_id"] not in existing]
    with judgements_path.open("a", encoding="utf-8") as output:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_video,
                    prediction,
                    annotations[prediction["video_id"]],
                    config,
                    args.response_retries,
                    args.transport_retries,
                    args.retry_delay,
                ): prediction["video_id"]
                for prediction in tasks
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
        [normalize_video_id(row) for row in read_jsonl(judgements_path)]
    )
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Accuracy: {metrics['accuracy']:.3f}")
    print(f"Coverage: {metrics['coverage']:.3f}")


if __name__ == "__main__":
    main()
