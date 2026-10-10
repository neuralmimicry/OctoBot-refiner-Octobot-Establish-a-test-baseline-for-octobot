#!/bin/bash

# Exit immediately if a command exits with a non-zero status 
set -e

# Save OctoBot config
if [[ -n "${OCTOBOT_CONFIG}" ]]; then
  echo "$OCTOBOT_CONFIG" | tee /octobot/user/config.json >/dev/null
fi

# Keep the image self-contained while leaving existing persistent tentacles
# untouched. Kubernetes' init container refreshes a volume by baked ID; this
# path supports fresh standalone/Docker volumes without a remote tentacle fetch.
BAKED_TENTACLES=/opt/octobot-baked-tentacles
RUNTIME_TENTACLES=/octobot/tentacles
if [[ -d "${BAKED_TENTACLES}" ]]; then
  if [[ ! -s "${BAKED_TENTACLES}/.swarmhpc-baked-id" || ! -s "${BAKED_TENTACLES}/.swarmhpc-baked-count" ]]; then
    echo "Embedded tentacle manifest is incomplete; refusing to start." >&2
    exit 1
  fi
  mkdir -p "${RUNTIME_TENTACLES}"
  shopt -s nullglob dotglob
  runtime_entries=("${RUNTIME_TENTACLES}"/*)
  if (( ${#runtime_entries[@]} == 0 )); then
    cp -R "${BAKED_TENTACLES}/." "${RUNTIME_TENTACLES}/"
  fi
  shopt -u nullglob dotglob
fi

# Start cloudflared tunnel
bash tunnel.sh

# Disable set -e 
set +e

# Start OctoBot using the installed console script
OctoBot "$@"
