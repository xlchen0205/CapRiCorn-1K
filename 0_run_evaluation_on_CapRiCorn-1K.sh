#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PREDICTIONS [OUTPUT_DIR] [extra evaluator arguments...]"
  echo
  echo "Default output dir: evaluation_results next to PREDICTIONS."
  echo "Default annotations: data/annotations.jsonl, resolved relative to this script."
  echo "Override with: ANNOTATIONS=/path/to/annotations.jsonl $0 ..."
  exit 2
fi

PREDICTIONS=$1
shift

if [[ $# -gt 0 && $1 != -* ]]; then
  OUTPUT_DIR=$1
  shift
else
  OUTPUT_DIR="$(cd -- "$(dirname -- "$PREDICTIONS")" && pwd)/evaluation_results"
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python}
ANNOTATIONS=${ANNOTATIONS:-"$SCRIPT_DIR/data/annotations.jsonl"}

mkdir -p "$OUTPUT_DIR"

"$PYTHON_BIN" "$SCRIPT_DIR/1_judge_accuracy_coverage.py" \
  --predictions "$PREDICTIONS" \
  --annotations "$ANNOTATIONS" \
  --output-dir "$OUTPUT_DIR" \
  "$@"

"$PYTHON_BIN" "$SCRIPT_DIR/2_judge_referential_consistency.py" \
  --predictions "$PREDICTIONS" \
  --stage1-results "$OUTPUT_DIR/1_judge_accuracy_coverage.jsonl" \
  --output-dir "$OUTPUT_DIR" \
  "$@"
