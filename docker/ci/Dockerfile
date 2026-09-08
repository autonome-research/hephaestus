# The pinned CI container image (Stage S disposition; repo_conventions.md
# renderer pin). Everything renderer-sensitive in the gates runs INSIDE this
# image: tests/render (G1 goldens), tests/stage4/test_g4_section_golden.py and
# `pnpm --dir web test:e2e` (G4.7 / INTERFACE.md §14). The image is consumed
# BY DIGEST from ci.yml — rebuilds that change the digest are renderer
# re-baselines and follow verification.md's golden-regeneration rule.
#
# Base is digest-pinned so the Mesa/llvmpipe build (the whole point of the
# image) cannot drift under the same tag.
FROM ubuntu:24.04@sha256:353675e2a41babd526e2b837d7ec780c2a05bca0164f7ea5dbbd433d21d166fc

ENV DEBIAN_FRONTEND=noninteractive
# Renderer + sandbox + build prerequisites — the same set ci.yml installs on
# stock runners, plus Playwright's browser dependencies.
RUN apt-get update -q && apt-get install -y -q --no-install-recommends \
      ca-certificates curl xz-utils git \
      bubblewrap \
      libegl1 libgl1 libgl1-mesa-dri libglx-mesa0 \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2t64 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Node 22.19.0 (repo pin) + pnpm 10 via corepack.
RUN curl -fsSL https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.xz \
      | tar -xJ -C /opt \
    && ln -s /opt/node-v22.19.0-linux-x64/bin/node /usr/local/bin/node \
    && ln -s /opt/node-v22.19.0-linux-x64/bin/npm /usr/local/bin/npm \
    && ln -s /opt/node-v22.19.0-linux-x64/bin/npx /usr/local/bin/npx \
    && ln -s /opt/node-v22.19.0-linux-x64/bin/corepack /usr/local/bin/corepack \
    && corepack enable --install-directory /usr/local/bin \
    && corepack prepare pnpm@10.18.3 --activate

# uv (pinned installer version); Python resolved per-repo by UV_PYTHON=3.13.
RUN curl -fsSL https://astral.sh/uv/0.9.28/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Playwright browsers are baked at the version web/package.json pins, so a job
# never downloads a browser at test time (and the browser build is part of the
# digest). PLAYWRIGHT_BROWSERS_PATH must be a path every job user can read.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN npm install -g @playwright/test@1.62.1 \
    && npx playwright install chromium \
    && chmod -R a+rX /opt/pw-browsers

# The Khronos glTF validator, PINNED (J-mirrors-and-dx-15). `mission_plan.md`
# states glTF validation as a project claim and
# `server/tests/test_http_gltf.py::..._khronos_...` is the lane that attempts it;
# before this the binary existed in no image, so the test skipped on every
# machine and in every job and the claim had no lane at all. Pinned rather than
# floating for the same reason the renderer is: a validator-adjacent gate that
# drifts under a moving version is what this image exists to prevent.
#
# Installed as `gltf_validator`, which is the name the test's PATH probe uses
# first. Once ci.yml's digest is bumped to an image built from this file, that
# job also sets HEPHAESTUS_REQUIRE_GLTF_VALIDATOR=1 and the test fails by name
# instead of skipping — the fail-rather-than-skip policy the renderer gate sets.
ARG GLTF_VALIDATOR_VERSION=2.0.0-dev.3.10
RUN curl -fsSL -o /tmp/gltf_validator.tar.xz \
      "https://github.com/KhronosGroup/glTF-Validator/releases/download/${GLTF_VALIDATOR_VERSION}/gltf_validator-${GLTF_VALIDATOR_VERSION}-linux64.tar.xz" \
    && tar -xJf /tmp/gltf_validator.tar.xz -C /usr/local/bin gltf_validator \
    && rm -f /tmp/gltf_validator.tar.xz \
    && chmod a+rx /usr/local/bin/gltf_validator \
    && gltf_validator --version

# Surfaceless EGL on llvmpipe — the spike-recorded configuration.
ENV EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1
