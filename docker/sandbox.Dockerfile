FROM python:3.12-slim

# Prevent interactive prompts and disable bytecode creation during build
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install testing and linting tools allowlisted for sandbox execution
RUN pip install --no-cache-dir pytest ruff

# Create dedicated non-root user and group with UID/GID 1000
RUN groupadd -g 1000 sandboxgroup && \
    useradd -u 1000 -g sandboxgroup -m -s /bin/bash sandboxuser

# Prepare workspace mount target and temporary storage directories
RUN mkdir -p /workspace /tmp/pycache /tmp/ruff_cache && \
    chown -R sandboxuser:sandboxgroup /workspace /tmp

USER sandboxuser
WORKDIR /workspace

CMD ["python3"]