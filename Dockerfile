FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/ ./
COPY assets/ciroot-harness-logo.png /build/assets/ciroot-harness-logo.png
COPY src/research_harness/examples/investigation/ /build/src/research_harness/examples/investigation/
RUN npm run build

FROM python:3.12-slim AS builder
WORKDIR /build/app
ARG RH_BUILD_HEAD=unknown
ARG RH_DIRTY_FILE_HASHES_JSON=
ENV RH_BUILD_HEAD=${RH_BUILD_HEAD} RH_DIRTY_FILE_HASHES_JSON=${RH_DIRTY_FILE_HASHES_JSON}
RUN python -m venv /opt/venv
COPY pyproject.toml ./
COPY src/ ./src/
COPY requirements/ ./requirements/
COPY packaging/build_manifest.py ./packaging/build_manifest.py
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
RUN /opt/venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements/core-lock.txt \
 && /opt/venv/bin/python -m pip wheel --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation --wheel-dir /build/core-wheel . \
 && /opt/venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --no-deps /build/core-wheel/*.whl \
 && PYTHONPATH=/build/app/src /opt/venv/bin/python packaging/build_manifest.py --manifest /build/output/build-manifest.json --demo-dir /build/output/demo --core-wheel /build/core-wheel/*.whl

FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    RH_PROFILE=research RH_HOST=0.0.0.0 RH_PORT=8765 \
    RH_WORKSPACE=/var/lib/research-harness/workspace \
    RH_LIBRARY_WORKSPACE=/var/lib/research-harness/library \
    RH_DEMO_SNAPSHOT=/app/deployment/demo_snapshot \
    RH_STATIC_DIR=/app/frontend/dist
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /var/lib/research-harness/workspace /var/lib/research-harness/library \
 && chown -R 10001:10001 /var/lib/research-harness
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/frontend/dist /app/frontend/dist
COPY --from=builder /build/output/demo /app/deployment/demo_snapshot
COPY --from=builder /build/output/build-manifest.json /app/deployment/build-manifest.json
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "research_harness.gui"]
