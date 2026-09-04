FROM python:3.12-slim
WORKDIR /workspace
COPY infra/docker/stage7m/requirements.txt /tmp/stage7m-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/stage7m-requirements.txt
