#!/bin/bash

# check python libs
python -m pip freeze

# Tests must consume the exact tentacles embedded in the image built from this
# checkout. Do not mask them with a bind mount or download mutable `latest`.
BAKED_TENTACLES=/opt/octobot-baked-tentacles
RUNTIME_TENTACLES=/octobot/tentacles
if [[ ! -s "${BAKED_TENTACLES}/.swarmhpc-baked-id" || ! -s "${BAKED_TENTACLES}/.swarmhpc-baked-count" ]]; then
    echo "Expected checked-out tentacles embedded in the image" >&2
    exit 1
fi
count="$(cat "${BAKED_TENTACLES}/.swarmhpc-baked-count")"
if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count < 150 )); then
    echo "Embedded tentacle count is invalid or incomplete: ${count}" >&2
    exit 1
fi
mkdir -p "${RUNTIME_TENTACLES}"
shopt -s nullglob dotglob
runtime_entries=("${RUNTIME_TENTACLES}"/*)
if (( ${#runtime_entries[@]} == 0 )); then
    cp -R "${BAKED_TENTACLES}/." "${RUNTIME_TENTACLES}/"
fi
shopt -u nullglob dotglob
if [[ "$(cat "${RUNTIME_TENTACLES}/.swarmhpc-baked-id")" != "$(cat "${BAKED_TENTACLES}/.swarmhpc-baked-id")" ]]; then
    echo "Runtime tentacles do not match the baked image source" >&2
    exit 1
fi
echo "Using source-matched tentacles embedded in the tested image"

# The test image may also contain a tentacles package in site-packages. Import
# the embedded tree generated from this checkout first so tests exercise the
# exact patched source used by the image build.
export PYTHONPATH="/octobot${PYTHONPATH:+:$PYTHONPATH}"

# run tests
if [[ -n "${OCTOBOT_TEST_PATH:-}" ]]; then
    pytest -rw "${OCTOBOT_TEST_PATH}"
else
    pytest -rw --ignore=tentacles/Trading/Exchange tests tentacles
fi
