# DEMO_DEPLOYMENT_PLAN.md — Despliegue del demo (arquitectura aprobada)

> **Fecha:** 2026-09-11
> **Contexto:** demo cliente 4-min (máx. 240 s por track, `max_concurrent_dsp=1`, `on_demand`).
> **Estado:** arquitectura **BLOQUEADA por decisión del dueño del producto** — no hay alternativa de topología.

---

## 0. Arquitectura aprobada (regla absoluta)

| Componente | Plataforma | Responsabilidad |
|---|---|---|
| **FRONTEND** | **VERCEL** · `apps/studio` (Next.js) | UI, Mastering, Mezcla |
| **BACKEND** | **RAILWAY** · `apps/audiomind` (FastAPI) | `/api/upload`, análisis, `/api/session/*`, `/process`, DSP de mastering, cache de presets, generación WAV PCM24, download, cleanup/TTL |

**En Vercel NO se ejecuta nada de backend:** FastAPI, audiomind, Python DSP, `process_audio`, upload/mastering/WAV proxy, procesamiento ni almacenamiento de masters.

**Railway es SOLO backend DSP** — no se despliega `apps/studio` ahí. Si existe un antiguo servicio frontend en Railway **no se usa** para esta demo (puede detenerse luego).

### Flujo de red obligatorio

```
Browser → Vercel → Studio HTML/JS
Browser → Railway FastAPI → upload
Browser → Railway FastAPI → analysis / session / process
Railway FastAPI → Browser → original / master WAV
```

NO está permitido: `Browser → Vercel API → Railway`, `Railway → Vercel → Browser`, Server Actions → Railway, Vercel Functions → Audiomind, ni Next.js API Route proxeando audio.

### Estado de preparación del código (verificado)

| Requisito | Estado |
|---|---|
| Studio usa `NEXT_PUBLIC_API_URL=https://<backend-railway>/api` con llamadas directas del browser (upload XHR, WAV por URL) | ✅ ya implementado (`apps/studio/src/adapters/api/config.ts`, fallback local `http://localhost:8000/api`) |
| CORS de Audiomind autoriza el frontend | ✅ `settings.cors_origins` por env (`CORS_ORIGINS`); en local ya permite `http://localhost:3000`; al conocer la URL Vercel exacta → agregarla antes del smoke público |
| Sin proxys Next de mastering/upload/WAV | ✅ las únicas API routes (`src/app/voz/*`) son del agente de voz (`@midimastering/agent`), no tocan audiomind |

---

## 1. Railway: recursos y evidencia de RAM (verificar antes del canary)

### Distinción obligatoria: anunciado vs. asignado vs. detectado

| Concepto | Valor | Fuente |
|---|---|---|
| **Límite máximo anunciado del plan Hobby** | Up to 5 replicas, **8 vCPU / 8 GB RAM por réplica** | Pricing mostrado por el usuario (captura 2026-09-11) |
| **Recursos actualmente asignados al servicio** | **UNKNOWN** — no verificable desde el repo; verificar en el dashboard de Railway antes del canary | Railway console |
| **Configuración/default detectado (512 MB)** | 512 MB detectado/asumido para la configuración actual | Config observada durante la validación local |
| **Recursos facturables/créditos** | UNKNOWN — a cargo del dueño de la cuenta | Railway billing |

**512 MB detectado/asumido para la configuración actual; el pricing mostrado por el usuario anuncia hasta 8 GB RAM por réplica en Hobby. Debe verificarse el límite efectivo del servicio antes del canary.**

Este documento **NO declara "Hobby = NO-GO" como hecho confirmado**: el límite efectivo del servicio debe verificarse en Railway antes del canary. La tabla siguiente compara los picos reales contra la config de 512 MB **detectada/asumida**, no contra el máximo anunciado.

### Picos reales medidos vs. config 512 MB (detectada/asumida)

| Criterio | Pico real medido | 512 MB (asumido) | Resultado vs. 512 MB |
|---|---|---|---|
| Baseline server (app + librosa) | ~0.21 GB usable | 0.5 GB | ✅ arranca (41%) |
| Job DSP 45 s | 1.26–1.31 GB | 0.5 GB | ❌ 2.5× |
| Job DSP 60 s | 1.60–1.79 GB | 0.5 GB | ❌ 3.1–3.5× |
| Job DSP 210 s | 5.60 GB | 0.5 GB | ❌ 11× |
| Job DSP 240 s | 6.71–6.95 GB | 0.5 GB | ❌ 13.1–13.5× |

Con un servicio real configurado a **8 GB por réplica** (máximo anunciado del plan), 240 s queda **POTENCIALMENTE dentro del límite, pero con poco margen** (6.95 GB ≈ 87 % de 8 GB). Eso requiere canary real (§2, etapas 4–6): los picos de la tabla son la guía para elegir el plan de RAM; el veredicto final se toma con jobs reales en Railway.

Los picos medidos (validación local, `../evidence/DEMO_LOCAL_VALIDATION.md`) corresponden **exclusivamente al backend Railway** — el frontend Vercel no necesita esa RAM.

Plan mínimo sugerido por canary (ver §2): 45–60 s → **≥2 GB**; 210 s → **≥6 GB**; 240 s → **≥8 GB** (o aplicar la optimización de pico §3 antes de la etapa 240 s).

---

## 2. Orden de deployment (bloqueado)

1. Validación local completa — ✅ `../evidence/DEMO_LOCAL_VALIDATION.md`
2. Commits/push de la rama Demo — ✅ `demo/vercel-railway-client` (aprobado y ejecutado)
3. Railway **BACKEND solamente** (nunca `apps/studio`)
4. Railway canary: **15 / 45 / 60 s**
5. Si estable → **210 s**
6. Si estable y hay RAM → **240 s**
7. Solo si el backend Railway queda aprobado → desplegar `apps/studio` en **Vercel**
8. Configurar `NEXT_PUBLIC_API_URL` de Vercel → `https://<backend-railway>/api`
9. Configurar CORS en Railway para el dominio Vercel exacto
10. Public smoke test
11. Public 240 s test controlado

**Gates de la etapa 4–6 (canary):** cada duración reutiliza la evidencia del staircase local (45 s → 1.3 GB, 60 s → 1.8 GB, 210 s → 5.6 GB, 240 s → 6.95 GB) para elegir el plan de RAM; si el job falla por OOM o el tiempo de respuesta es inviable, se frena la escalada y se revisa RAM/optimización — nunca se despliega el frontend con un backend no aprobado.

---

## 3. Optimización del pico (trabajo futuro, NO bloquea el canary)

El pico actual (42 MB WAV → ≈6.95 GB working set, ×165) es desproporcionado. Candidatos para reducir a ≈2 GB y permitir 240 s en planes chicos:

1. Perfil de análisis librosa (STFT/mel/tempo/chroma) sobre 240 s — chunking o truncación de features.
2. Streaming/chunked DSP en la cadena de 13 etapas.
3. Float32 en toda la cadena (evitar copias float64).
4. Mono para análisis (el master final se mantiene estéreo).

Esto es un item de código aparte — la arquitectura de despliegue no depende de él.