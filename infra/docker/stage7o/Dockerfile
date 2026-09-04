FROM python:3.12-slim

WORKDIR /workspace

COPY infra/docker/stage7o/requirements.txt /tmp/stage7o-requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/stage7o-requirements.txt
