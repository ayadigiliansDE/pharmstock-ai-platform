FROM python:3.12-slim

WORKDIR /workspace
COPY infra/docker/stage7l/requirements.txt /tmp/stage7l-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/stage7l-requirements.txt
