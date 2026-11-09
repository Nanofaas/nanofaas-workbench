# Build from the repository root:
#   docker build -f images/supervisor/Dockerfile -t ghcr.io/nanofaas/workbench-supervisor:<version> .
# python:3.12-slim, Python 3.12.16 (multi-arch index digest)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

LABEL org.opencontainers.image.source=https://github.com/Nanofaas/nanofaas-workbench
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY supervisor/src /app
USER 65534:65534
ENTRYPOINT ["python", "-m", "workbench_supervisor"]
