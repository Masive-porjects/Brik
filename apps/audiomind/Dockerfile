# v3 — slim/glibc (onnxruntime solo tiene wheels manylinux; musl falla con ResolutionImpossible)
FROM python:3.11-slim

# Build amigable con poca RAM (Railway 1GB):
# - GzipIndexes=false: no descomprime los indices gzip de apt en memoria
# - Languages=none / Pipeline-Depth=0: menos RAM y red en apt update
# - glibc: onnxruntime/demucs NO tienen wheels musllinux (en Alpine el resolver
#   fallaba con ResolutionImpossible). Slim = wheels manylinux disponibles.
RUN apt-get update \
    -o Acquire::GzipIndexes=false \
    -o Acquire::Languages=none \
    -o Acquire::http::Pipeline-Depth=0 \
    && apt-get install -y --no-install-recommends \
    libatomic1 \
    libsndfile1 \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache de Hugging Face en un path CONOCIDO y estable.
#
# Antes los pesos se bajaban dentro del request: la primera separacion de stems
# descargaba ~300 MB y compilaba la sesion ONNX mientras el servidor ya estaba
# vivo. En un contenedor chico eso es un pico de memoria que el kernel mata
# ("Killed", sin traceback de Python) -> 502 con el job ya completado en
# Supabase. Horneando los pesos aca, el runtime solo mapea memoria.
#
# Este ENV vive en la imagen, asi que build y runtime comparten el mismo path y
# la separacion en runtime no vuelve a descargar nada.
ENV HF_HOME=/opt/hf-cache

# onnxruntime primero: demucs-onnx pide >=1.17 y sin un wheel instalado el
# resolver puede intentar compilarlo (o fallar la resolucion). Con onnxruntime
# ya instalado, el paso siguiente lo ve satisfecho y no lo re-resuelve.
COPY pyproject.toml .
RUN pip install --no-cache-dir onnxruntime \
    && pip install --no-cache-dir $(python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies'];print(' '.join(d))") \
    && pip install --no-cache-dir setuptools wheel

# Codigo: instalar el paquete editable SIN re-bajar ni resolver dependencias.
# Editable es obligatorio: config.py resuelve uploads/outputs con Path(__file__).parent*3
# y APUNTA A /app/src/audiomind/... — con pip install . normal, __file__ estaria en
# site-packages y las rutas de archivos se romperian.
COPY src/ src/
RUN pip install --no-cache-dir --no-deps --no-build-isolation -e .

# HORNEAR los pesos de HTDemucs en la imagen.
#
# demucs_onnx.prewarm() existe justamente para esto ("Pre-download + compile
# sessions... where the first separate call would otherwise trigger a 300 MB
# download"). OJO con dos trampas aca:
#
#  1. prewarm() SIN argumentos hornea "htdemucs_ft" (bag-of-specialists), pero
#     processing/splitter.py llama separate(model="htdemucs"). Hay que pasar el
#     modelo explicito o queda horneado uno que la app nunca usa.
#  2. La precision debe coincidir con la que pide runtime. split_audio() llama
#     separate() sin argumento precision, o sea fp32 (el default). Si horneamos
#     solo fp16, el runtime vuelve a descargar el fp32.
#
# Si la descarga falla el build se cae a proposito: una imagen sin pesos
# horneados reintroduce el OOM en runtime, y eso es peor que un deploy
# postergado que un 502 silencioso.
#
# prewarm() devuelve dict[str, Path]: los values son PosixPath y NO son JSON
# serializables, asi que el log usa str() y no json.dumps() (un json.dumps()
# aca tumbaba el build entero con TypeError, despues de haber descarga bien).
RUN python -c "import os,pathlib,demucs_onnx; baked=demucs_onnx.prewarm(['htdemucs'], precision='fp32'); print('baked:', {k: str(v) for k, v in baked.items()}); root=pathlib.Path(os.environ['HF_HOME']); print('HF cache MiB:', sum(f.stat().st_size for f in root.rglob('*') if f.is_file())//1048576)"

RUN mkdir -p uploads outputs

# Railway provee $PORT (tipicamente 8080); si no existe, cae a 8080 para
# coincidir con el puerto de red configurado en Railway (Networking).
# IMPORTANTE: el modulo es audiomind.main:app (src-layout), NO main:app.
EXPOSE 8080

CMD ["sh", "-c", "uvicorn audiomind.main:app --host 0.0.0.0 --port ${PORT:-8080}"]