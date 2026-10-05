#!/usr/bin/env bash
# Rebuild patches/ and series from a git branch holding one commit per patch.
# Each commit message must carry a "Tag: <tag>" line (see series header).
# Typical refresh after an upstream bump:
#   git -C WORK checkout -b refresh NEW_UPSTREAM_REF
#   git -C WORK am -3 "$OVERLAY"/patches/*.patch      # resolve conflicts, `git am --continue`
#   ./export.sh WORK NEW_UPSTREAM_REF refresh && update ref= in UPSTREAM
# usage: export.sh REPO BASE_REF [HEAD_REF]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$1"; base="$2"; head="${3:-HEAD}"
header="$(sed -n '/^#/p' "$here/series")"
rm -f "$here"/patches/*.patch
git -C "$repo" format-patch -q --zero-commit --no-signature --full-index -o "$here/patches" "$base..$head"
{
  printf '%s\n' "$header"
  for p in "$here"/patches/*.patch; do
    tag="$(sed -n 's/^Tag: //p' "$p" | head -1)"
    [ -n "$tag" ] || { echo "missing Tag: line in $p" >&2; exit 1; }
    echo "patches/$(basename "$p") $tag"
  done
} > "$here/series.new"
mv "$here/series.new" "$here/series"
echo "exported $(grep -c '^patches/' "$here/series") patches; now run ./selftest.sh $base"
