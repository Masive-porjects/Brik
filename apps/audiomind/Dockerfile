# AudioMind Backend - Python FastAPI service
# Builds the DSP mastering engine with all dependencies

# Python 3.12 is required by librosa 1.0, and it must match the version CI
# installs and pyproject declares: while the image ran 3.11 and development ran
# 3.12, librosa resolved to 0.11 in production and 1.0 locally, and the two
# disagreed about beat detection. tests/test_runtime_python_contract.py keeps
# the three declarations from drifting apart again.
FROM python:3.12-slim

# System deps for audio processing (librosa, pedalboard, demucs, soxr)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsox-dev \
    libsndfile1 \
    libsndfile1-dev \
    build-essential \
    cmake \
    pkg-config \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# src/ must be present before the editable install: setuptools discovers the
# package from src/ ([tool.setuptools.packages.find] where = ["src"]), so
# `pip install -e .` fails if the tree is missing.
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir demucs-onnx==0.3.4

# Prewarm Demucs ONNX weights at build time to avoid runtime downloads
# This must match the precision in config.py (demucs_precision = "fp16weights")
# and the model used in splitter.py (model="htdemucs").
#
# The distribution is called demucs-onnx but it installs the module as
# demucs_onnx, and this step and the app both import that name. 51a18e1 rewrote
# it as `from demucs.onnx import prewarm`, which no package provides, so the
# image build died here on every deploy from 2026-10-22 on, while CI stayed
# green because CI never builds the image.
RUN python -c "from demucs_onnx import prewarm; baked = prewarm(['htdemucs'], precision='fp16weights'); print('baked:', {k: str(v) for k, v in baked.items()})"

# Create necessary directories. samples/ is gitignored and excluded by
# .dockerignore (fixtures come from scripts/generate_samples.py), so it is
# created empty instead of copied — `COPY samples/` breaks the build.
RUN mkdir -p uploads outputs projects prebuilt samples

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUDIOMIND_DEMUCS_PRECISION=fp16weights \
    AUDIOMIND_DEMUCS_ISOLATED=true \
    AUDIOMIND_DEMUCS_THREADS=4 \
    AUDIOMIND_DEMUCS_TIMEOUT_SECONDS=1800 \
    AUDIOMIND_MAX_CONCURRENT_DSP=1 \
    AUDIOMIND_PRERENDER_MODE=on_demand \
    AUDIOMIND_DEMO_MAX_DURATION_SECONDS=240 \
    AUDIOMIND_MAX_FILE_SIZE_MB=100 \
    AUDIOMIND_SESSION_TTL_MINUTES=60 \
    AUDIOMIND_SESSION_STORE_BACKEND=auto

# Expose port (Railway sets $PORT)
EXPOSE 8000

# Health check. Railway injects $PORT; the same default as the start command
# keeps a plain `docker run` working.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os, httpx; httpx.get('http://localhost:' + os.environ.get('PORT', '8000') + '/health', timeout=5).raise_for_status()" || exit 1

# Start command: expands $PORT at runtime (exec keeps uvicorn as PID 1 so it
# receives Railway's SIGTERM on redeploy).
CMD ["sh", "-c", "exec uvicorn audiomind.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]