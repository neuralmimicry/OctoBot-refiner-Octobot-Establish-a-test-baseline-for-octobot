#!/usr/bin/env bash
# Self-test for the overlay: fetch the pinned upstream ref fresh, apply the
# queue, re-apply (must be UNCHANGED), and --check (must be CHECK-OK).
# usage: selftest.sh [UPSTREAM_REF]   (default: ref= in ./UPSTREAM)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(sed -n 's/^repo=//p' "$here/UPSTREAM")"
ref="${1:-$(sed -n 's/^ref=//p' "$here/UPSTREAM")}"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git init -q "$work"
git -C "$work" fetch -q --depth 1 "$repo" "$ref"
git -C "$work" checkout -q FETCH_HEAD
echo "upstream $(git -C "$work" rev-parse HEAD)"
first="$(python3 "$here/apply.py" --target "$work" | tee /dev/stderr | tail -1)"
[ "$first" = "UPDATED" ] || { echo "first apply did not report UPDATED: $first" >&2; exit 1; }
second="$(python3 "$here/apply.py" --target "$work" | tail -1)"
[ "$second" = "UNCHANGED" ] || { echo "second apply is not idempotent: $second" >&2; exit 1; }
check="$(python3 "$here/apply.py" --target "$work" --check | tail -1)"
[ "$check" = "CHECK-OK" ] || { echo "--check failed: $check" >&2; exit 1; }
echo "SELFTEST-OK $(grep -c '^patches/' "$here/series") patches on $ref"
