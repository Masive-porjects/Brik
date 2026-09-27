# Mock del bridge para el Live Engine: emite LiveParams por WS :8765.
# Build context = raiz del repo.
FROM python:3.12-slim

WORKDIR /app

COPY simulator/requirements.txt simulator/requirements.txt
RUN pip install --no-cache-dir -r simulator/requirements.txt

COPY simulator ./simulator

EXPOSE 8765

# --host 0.0.0.0: sin esto el server solo escucha en la interfaz interna
# del contenedor y el puerto publicado no responde desde el host.
ENTRYPOINT ["python", "-m", "simulator.main"]
CMD ["--mode", "server", "--scenario", "sweep", "--host", "0.0.0.0", "--port", "8765", "--loop"]
