# AudioMind Backend - Python FastAPI service
# Builds the DSP mastering engine with all dependencies

FROM python:3.11-slim

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

# Copy pyproject.toml first for better layer caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir demucs-onnx==0.3.4

# Prewarm Demucs ONNX weights at build time to avoid runtime downloads
# This must match the precision in config.py (demucs_precision = "fp16weights")
# and the model used in splitter.py (model="htdemucs")
RUN python -c "from demucs.onnx import prewarm; prewarm(['htdemucs'], precision='fp16weights')"

# Copy source code
COPY src/ ./src/
COPY samples/ ./samples/

# Create necessary directories
RUN mkdir -p uploads outputs projects prebuilt

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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

# Start command
CMD ["uvicorn", "audiomind.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]