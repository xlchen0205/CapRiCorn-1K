#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 PREDICTIONS OUTPUT_DIR [extra evaluator arguments...]"
  echo
  echo "PREDICTIONS must use video_id strings, e.g. 0001."
  echo "Pass judge options such as --model, --base-url, --api-key, and --workers"
  echo "after OUTPUT_DIR."
  exit 2
fi

PREDICTIONS=$1
OUTPUT_DIR=$2
shift 2

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ANNOTATIONS="$SCRIPT_DIR/data/annotations_vision_only.jsonl"

export ANNOTATIONS
"$SCRIPT_DIR/0_run_evaluation_on_CapRiCorn-1K.sh" \
  "$PREDICTIONS" \
  "$OUTPUT_DIR" \
  "$@"
