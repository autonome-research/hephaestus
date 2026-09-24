FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS install
ARG TARGETARCH

COPY docker/executor/requirements.lock /build/requirements.lock
COPY dist/executor-wheelhouse/ /wheelhouse/
COPY dist/executor-native/ /native-packages/
COPY docker/executor/fetch_native_runtime.py \
     docker/executor/native-amd64.lock.json \
     docker/executor/native-arm64.lock.json \
     /build/native-lock/
COPY docker/executor/fonts.conf /build/fonts.conf

RUN --network=none python /build/native-lock/fetch_native_runtime.py \
      "$TARGETARCH" /native-packages --verify-only
RUN --network=none set -eu; \
    mkdir -p /opt/hephaestus/native; \
    for package in /native-packages/*.deb; do \
         dpkg-deb --extract "$package" /opt/hephaestus/native; \
       done; \
    cp /build/fonts.conf /opt/hephaestus/native/fonts.conf; \
    mkdir -p /etc/fonts; \
    ln -s /opt/hephaestus/native/fonts.conf /etc/fonts/fonts.conf; \
    rm -rf /opt/hephaestus/native/usr/share/doc \
           /opt/hephaestus/native/usr/share/man
RUN python -m venv /opt/hephaestus
RUN --network=none /opt/hephaestus/bin/python -m pip install \
      --no-index \
      --find-links=/wheelhouse \
      --only-binary=:all: \
      --require-hashes \
      --no-deps \
      -r /build/requirements.lock
RUN --network=none /opt/hephaestus/bin/python -m pip install \
      --no-index \
      --find-links=/wheelhouse \
      --only-binary=:all: \
      --require-hashes \
      --no-deps \
      -r /wheelhouse/local-requirements.lock
RUN --network=none /opt/hephaestus/bin/python -m pip check
RUN --network=none test -z "$(/opt/hephaestus/bin/python -m pip list --format=freeze \
      | grep -E '^(pillow|pygltflib|pyrender)==')"
RUN --network=none env -i \
      'LD_LIBRARY_PATH=/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB' \
      /opt/hephaestus/bin/python -I -c \
      'import build123d; assert build123d.Box(1, 2, 3).volume == 6.0'
RUN --network=none set -eu; \
    export LD_LIBRARY_PATH='/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB'; \
    linkage="$(find /opt/hephaestus -type f \
      \( -name '*.so' -o -name '*.so.*' \) -exec ldd '{}' \; 2>&1 || true)"; \
    case "$linkage" in *'not found'*) printf '%s\n' "$linkage" >&2; exit 1;; esac
RUN --network=none /opt/hephaestus/bin/python -I -m \
      hephaestus.core.executor.sandbox.oci_launcher manifest >/dev/null

FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

RUN mkdir /work /etc/fonts \
    && chmod 0755 /work \
    && ln -s /opt/hephaestus/native/fonts.conf /etc/fonts/fonts.conf
COPY --from=install /opt/hephaestus /opt/hephaestus

USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/usr/bin/env", "-i", "LD_LIBRARY_PATH=/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB", "/opt/hephaestus/bin/python", "-I", "-m", "hephaestus.core.executor.sandbox.oci_launcher"]
CMD []
