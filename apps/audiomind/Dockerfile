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

# HORNEAR los pesos de HTDemucs en la imagen, en fp16weights.
#
# demucs_onnx.prewarm() existe justamente para esto ("Pre-download + compile
# sessions... where the first separate call would otherwise trigger a 300 MB
# download").
#
# POR QUE fp16weights Y NO fp32: el OOM no era la descarga, era la inferencia.
# Los logs daban "Killed" sin traceback de Python con los pesos YA horneados
# (cero warnings de HF Hub): el kernel lo mata durante la separacion. El grafo
# fp32 son ~302 MiB de pesos en RAM contra ~158 MiB en fp16weights, mas las
# activaciones. Bajar el grafo a la mitad es lo que libera el pico.
#
# TRAMPAS (las dos costaron un deploy cada una):
#
#  1. prewarm() SIN argumentos hornea "htdemucs_ft" (bag-of-specialists), pero
#     processing/splitter.py llama separate(model="htdemucs"). Hay que pasar el
#     modelo explicito o queda horneado uno que la app nunca usa.
#  2. La precision debe COINCIDIR con la que pide runtime. demucs-onnx keyea su
#     cache por precision, asi que hornear fp32 mientras el runtime pide
#     fp16weights (o al reves) no elimina la descarga: la corre al primer
#     request, que es justo lo que Rompemos. La fuente de verdad del runtime es
#     settings.demucs_precision (ver processing/splitter.py).
#
# Si la descarga falla el build se cae a proposito: una imagen sin pesos
# horneados reintroduce el OOM en runtime, y eso es peor que un deploy
# postergado que un 502 silencioso.
#
# prewarm() devuelve dict[str, Path]: los values son PosixPath y NO son JSON
# serializables, asi que el log usa str() y no json.dumps() (un json.dumps()
# aca tumbaba el build entero con TypeError, despues de haber descarga bien).
RUN python -c "import os,pathlib,demucs_onnx; baked=demucs_onnx.prewarm(['htdemucs'], precision='fp16weights'); print('baked:', {k: str(v) for k, v in baked.items()}); root=pathlib.Path(os.environ['HF_HOME']); print('HF cache MiB:', sum(f.stat().st_size for f in root.rglob('*') if f.is_file())//1048576)" \
    && python -c "import pathlib,os; f=[p for p in pathlib.Path(os.environ['HF_HOME']).rglob('*fp16weights*.onnx')]; assert f, 'fp16weights NO horneado -> runtime descargaria en cada request'; print('fp16weights OK:', f[0].name, f[0].stat().st_size//1048576, 'MiB')"

RUN mkdir -p uploads outputs

# Railway provee $PORT (tipicamente 8080); si no existe, cae a 8080 para
# coincidir con el puerto de red configurado en Railway (Networking).
# IMPORTANTE: el modulo es audiomind.main:app (src-layout), NO main:app.
EXPOSE 8080

CMD ["sh", "-c", "uvicorn audiomind.main:app --host 0.0.0.0 --port ${PORT:-8080}"]