# Experimental ARM64 renderer. Independent base/dependency closure; not FROM the CAD image.
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS install
ARG TARGETARCH
COPY docker/executor/requirements.lock /build/cad-requirements.lock
COPY docker/renderer/requirements.lock /build/render-requirements.lock
COPY docker/renderer/build-requirements.lock /build/build-requirements.lock
COPY docker/executor/fetch_native_runtime.py /build/native-lock/fetch_native_runtime.py
COPY docker/renderer/native-arm64.lock.json /build/native-lock/native-arm64.lock.json
COPY docker/executor/fonts.conf /build/fonts.conf
COPY dist/renderer-wheelhouse/ /wheelhouse/
COPY dist/renderer-native/ /native-packages/
COPY dist/renderer-python/ /render-packages/
RUN --network=none test "$TARGETARCH" = arm64 && python /build/native-lock/fetch_native_runtime.py "$TARGETARCH" /native-packages --verify-only
RUN --network=none set -eu; mkdir -p /opt/hephaestus/native; \
    for package in /native-packages/*.deb; do dpkg-deb --extract "$package" /opt/hephaestus/native; done; \
    cp /build/fonts.conf /opt/hephaestus/native/fonts.conf; \
    mkdir -p /etc/fonts; ln -s /opt/hephaestus/native/fonts.conf /etc/fonts/fonts.conf; \
    rm -rf /opt/hephaestus/native/usr/share/doc /opt/hephaestus/native/usr/share/man
# PyOpenGL 3.1.0 only ships an sdist. Its exact root-lock hash is checked by pip;
# build-only setuptools/wheel are separately pinned and never copied to final.
RUN --network=none python -m venv /buildenv && /buildenv/bin/pip install --no-index --find-links=/render-packages --require-hashes -r /build/build-requirements.lock
COPY docker/renderer/pyopengl-source.lock /build/pyopengl-source.lock
RUN --network=none SOURCE_DATE_EPOCH=0 /buildenv/bin/pip wheel --no-index --find-links=/render-packages --no-deps --no-build-isolation --require-hashes -r /build/pyopengl-source.lock -w /built
RUN --network=none python -c 'import pathlib,hashlib; p=next(pathlib.Path("/built").glob("*.whl")); pathlib.Path("/built/requirements.lock").write_text("PyOpenGL==3.1.0 --hash=sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()+"\n")'
RUN --network=none python -m venv /opt/hephaestus && /opt/hephaestus/bin/pip install --no-index --find-links=/wheelhouse --only-binary=:all: --require-hashes --no-deps -r /build/cad-requirements.lock -r /wheelhouse/local-requirements.lock
RUN --network=none /opt/hephaestus/bin/pip install --no-index --find-links=/render-packages --find-links=/built --only-binary=:all: --require-hashes --no-deps -r /build/render-requirements.lock -r /built/requirements.lock
RUN --network=none /opt/hephaestus/bin/pip check
RUN --network=none env -i 'LD_LIBRARY_PATH=/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB' /opt/hephaestus/bin/python -I -c 'import build123d; assert build123d.Box(1,2,3).volume == 6.0'
RUN --network=none set -eu; \
    export LD_LIBRARY_PATH='/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB'; \
    linkage="$(find /opt/hephaestus -type f \( -name '*.so' -o -name '*.so.*' \) -exec ldd '{}' \; 2>&1 || true)"; \
    case "$linkage" in *'not found'*) printf '%s\n' "$linkage" >&2; exit 1;; esac
RUN --network=none /opt/hephaestus/bin/python -I -m hephaestus.core.render.oci_launcher manifest >/dev/null
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
RUN mkdir /work /inputs /etc/fonts && chmod 0755 /work /inputs && ln -s /opt/hephaestus/native/fonts.conf /etc/fonts/fonts.conf
COPY --from=install /opt/hephaestus /opt/hephaestus
# PyOpenGL 3.1.0 calls ctypes.util.find_library, which reads the image's linker
# cache, not our dynamic $LIB loader path. This is image-local immutable setup,
# never a host/daemon change or workload-controlled path.
RUN printf '%s\n' /opt/hephaestus/native/lib/aarch64-linux-gnu /opt/hephaestus/native/usr/lib/aarch64-linux-gnu > /etc/ld.so.conf.d/hephaestus-renderer.conf && /sbin/ldconfig
USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/usr/bin/env", "-i", "LD_LIBRARY_PATH=/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB", "/opt/hephaestus/bin/python", "-I", "-m", "hephaestus.core.render.oci_launcher"]
CMD []
