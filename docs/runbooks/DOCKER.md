# DOCKER.md — Stack local con Docker Compose

> Alternativa dockerizada a `SETUP.md` para levantar el stack completo sin
> instalar Python/bun en el host. Solo necesitas Docker Desktop.
> Stack: Studio (Next.js :3000) · AudioMind (FastAPI :8000).

---

## 0. Requisitos

| Requisito | Versión | Por qué |
|---|---|---|
| Docker | ≥ 24 con Compose v2 | `docker compose` (plugin) |
| RAM libre | ~4 GB para el primer build | audiomind compila deps DSP pesadas (librosa, pedalboard, demucs-onnx) |

---

## 1. Levantar el stack

```bash
docker compose up --build        # primer build: varios minutos (deps DSP + next build)
docker compose up                # subsecuentes: usa cache
docker compose up -d             # en segundo plano
docker compose down              # detiene todo (los volúmenes sobreviven)
docker compose down -v           # detiene y BORRA uploads/outputs persistidos
```

**Esperado:** `docker compose ps` muestra los 2 servicios `healthy`.

| Servicio | URL | Qué es |
|---|---|---|
| `studio` | http://localhost:3000 | UI de mastering + pestaña Live (build de producción, `next start` standalone) |
| `audiomind` | http://localhost:8000/health | DSP de mastering (`{"status":"ok","service":"AudioMind"}`) |

---

## 2. Decisiones de diseño (por qué es así)

- **Bridge y simulator fueron removidos del producto.** `apps/bridge/` (MIDI → WS) y el módulo `simulator/` ya no existen — el Live Engine es standalone (knobs del navegador, sin WebSocket ni MIDI). El servicio `simulator` que quedaba en el compose (build desde el `simulator/Dockerfile` sobreviviente) apuntaba a un módulo Python inexistente → **se quitó de `docker-compose.yml`** (23-Sep, commit `093946c`). Ver `../ESTADO_PROYECTO.md` §5.
- **`NEXT_PUBLIC_API_URL` es un build-arg.** Las `NEXT_PUBLIC_*` se inlinean en
  el bundle durante `next build` — cambiarla exige `docker compose build studio`.
  El default `http://localhost:8000/api` es correcto porque el browser corre en
  el host y llega a audiomind por el puerto publicado.
- **Studio corre standalone.** `next.config.ts` usa `output: "standalone"` +
  `outputFileTracingRoot` en la raíz del monorepo; el Dockerfile copia solo lo
  trazado (imagen final sin `node_modules` completos). `next start` y los
  deploys en Vercel/Railway no se ven afectados.
- **Convex no es obligatorio.** El provider de la app es un passthrough
  (`ConvexClientProvider`); el studio compila y corre sin
  `NEXT_PUBLIC_CONVEX_URL`. Si necesitas auth/datos reales, pásala como
  build-arg: `docker compose build --build-arg NEXT_PUBLIC_CONVEX_URL=https://… studio`.
- **`GEMINI_API_KEY` / ElevenLabs** son envs de runtime de las rutas `/voz/*`.
  Sin ellas esas rutas responden degradado (comportamiento ya existente).
  Para habilitarlas: `environment:` en el servicio `studio` o un `.env` junto
  al compose.

---

## 3. Persistencia

- `audiomind-uploads` y `audiomind-outputs` son volúmenes nombrados: los WAV
  subidos y los masters sobreviven a `restart`/`down`.
- **Las sesiones siguen siendo en memoria** (regla no negociable del backend):
  reiniciar el contenedor pierde el estado de sesión — el frontend muestra
  "Tu sesión anterior expiró". Igual que en el run local.

---

## 4. Verificación

```bash
docker compose ps                                   # 2 servicios healthy
curl http://localhost:8000/health                   # {"status":"ok","service":"AudioMind"}
curl -I http://localhost:3000                       # 200
# Live Engine: pestaña "Live" del studio — los knobs se operan desde la UI
# (standalone, sin websocket ni simulator).
```

---

## 5. Pitfalls

| # | Pitfall | Detalle |
|---|---|---|
| 1 | Servicio `simulator` | **removido del compose** (23-Sep, `093946c`) — el módulo Python no existe; `simulator/Dockerfile` es un huérfano que se puede borrar |
| 2 | Cambiar `NEXT_PUBLIC_API_URL` | es build-arg: `docker compose build studio` (no basta `restart`) |
| 3 | Primer build lento | demucs-onnx/onnxruntime pesan ~1 GB; los rebuilds usan cache |
| 4 | `docker compose up` viejo | tras cambios de código: `docker compose up --build` |
