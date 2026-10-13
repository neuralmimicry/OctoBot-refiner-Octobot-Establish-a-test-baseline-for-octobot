FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node_runtime

FROM python:3.13-slim-trixie AS base

WORKDIR /tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        gcc \
        binutils \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libxslt-dev \
        libjpeg62-turbo-dev \
        libopenblas-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Skip cryptography rust compilation (required for armv7 builds)
ENV CRYPTOGRAPHY_DONT_BUILD_RUST=1

COPY dist/octobot-*.whl /tmp/
COPY extra_requirements.txt /tmp/
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir /tmp/octobot-*.whl \
    && pip install --no-cache-dir -r /tmp/extra_requirements.txt

FROM python:3.13-slim-trixie

ARG TENTACLES_URL_TAG=""
ARG VERSION=""
ARG SOURCE_REPOSITORY=""
ENV TENTACLES_URL_TAG=$TENTACLES_URL_TAG
ENV VERSION=$VERSION

LABEL maintainer="Drakkar-Software" \
      version="${VERSION}" \
      description="OctoBot - Cryptocurrency trading bot" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}"

WORKDIR /octobot

COPY --from=base /opt/venv /opt/venv
COPY octobot/config /octobot/octobot/config
COPY start.py /octobot/
COPY docker/* /octobot/
# The image is built only after the workflow exports and installs tentacles
# from this exact checked-out source tree. Keep them separate from the runtime
# volume so Kubernetes can copy this immutable tree into its persistent volume.
COPY tentacles/ /opt/octobot-baked-tentacles/
# Production checks source-export prerequisites before taking its baked path.
# Keep the same checked-out source and pinned Node toolchain available there.
COPY packages/tentacles/ /opt/octobot-source/packages/tentacles/
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules/ /usr/local/lib/node_modules/

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libxslt-dev \
        libxcb-xinput0 \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        libblas-dev \
        liblapack-dev \
        libopenblas-dev \
        libopenjp2-7 \
        libtiff-dev \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x docker-entrypoint.sh \
    && chmod +x tunnel.sh \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version \
    && npm --version \
    && test -s /opt/octobot-baked-tentacles/.swarmhpc-baked-count \
    && test -s /opt/octobot-baked-tentacles/.swarmhpc-baked-id

ENV PATH="/opt/venv/bin:$PATH"

VOLUME /octobot/backtesting
VOLUME /octobot/logs
VOLUME /octobot/tentacles
VOLUME /octobot/user

# Node API (OctoBot node mode)
EXPOSE 8000
# Standalone web UI (5001) + up to 10 spawned process-bot web interfaces (5001-5010)
EXPOSE 5001-5010

HEALTHCHECK --interval=15s --timeout=10s --retries=5 \
    CMD curl --fail --silent --show-error --max-time 5 \
        http://127.0.0.1:5001/ >/dev/null

ENTRYPOINT ["./docker-entrypoint.sh"]
