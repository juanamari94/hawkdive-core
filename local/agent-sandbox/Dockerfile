FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid 1000 --create-home agent \
    && mkdir /workspace \
    && chown agent:agent /workspace

USER agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
