FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Security: dedicated unprivileged user for untrusted workspace execution
RUN useradd -u 1000 -m -s /bin/bash sandboxuser

WORKDIR /workspace
RUN chown -R sandboxuser:sandboxuser /workspace

USER sandboxuser

CMD ["tail", "-f", "/dev/null"]