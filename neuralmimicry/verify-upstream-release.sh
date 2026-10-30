#!/usr/bin/env bash
# Verify application code and declared release together. A new fork image or a
# changed version string alone is not evidence that an upstream upgrade landed.
set -euo pipefail
nm_root=$(git rev-parse --show-toplevel)
nm_manifest="$nm_root/neuralmimicry/octobot-overlay/UPSTREAM"
nm_ref=$(sed -n 's/^ref=//p' "$nm_manifest")
nm_release=$(sed -n 's/^release=//p' "$nm_manifest")
[[ "$nm_ref" =~ ^[a-f0-9]{40}$ && -n "$nm_release" ]]
nm_version=$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$nm_root/octobot/__init__.py")
[[ "$nm_version" == "$nm_release" ]] || {
  printf 'Release mismatch: application=%s declared=%s\n' "$nm_version" "$nm_release" >&2
  exit 1
}
# Checkout actions may use a shallow merge checkout. Fetch only the reviewed
# commit and bounded ancestry when needed; do not select a mutable branch.
if ! git cat-file -e "$nm_ref^{commit}" 2>/dev/null; then
  git fetch --no-tags --depth=1 "$(sed -n 's/^repo=//p' "$nm_manifest")" "$nm_ref"
fi
if ! git merge-base --is-ancestor "$nm_ref" HEAD; then
  if [[ $(git rev-parse --is-shallow-repository) == true ]]; then
    git fetch --unshallow origin
  fi
  git merge-base --is-ancestor "$nm_ref" HEAD || {
    printf 'Declared upstream release is absent from source ancestry: %s\n' "$nm_ref" >&2
    exit 1
  }
fi
printf 'Verified upstream %s at %s\n' "$nm_release" "$nm_ref"
