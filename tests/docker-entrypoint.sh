#!/bin/bash

# check python libs
python -m pip freeze

# Container tests mount the tentacles generated from this exact checkout. Do
# not replace them with the mutable remote `latest` archive: it may target
# package APIs from a different OctoBot revision.
if [[ "${OCTOBOT_TEST_TENTACLES_SOURCE:-}" == "mounted" ]]; then
    if ! compgen -G "tentacles/*" >/dev/null; then
        echo "Expected checkout tentacles in the mounted /octobot/tentacles directory" >&2
        exit 1
    fi
    echo "Using tentacles generated from the tested checkout"
else
    # install tentacles
    if OctoBot tentacles --install -a ; then
        echo "Tentacles successfully installed"
    else
        unset TENTACLES_REPOSITORY
        export TENTACLES_URL_TAG=latest
        OctoBot tentacles --install -a
    fi
fi

# run tests
pytest -rw --ignore=tentacles/Trading/Exchange tests tentacles
