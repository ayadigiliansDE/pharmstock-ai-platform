FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace
COPY infra/docker/stage7k5/requirements.txt /tmp/stage7k5-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/stage7k5-requirements.txt

ENV PYTHONPATH=/workspace:/workspace/src
