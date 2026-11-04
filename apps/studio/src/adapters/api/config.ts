/**
 * Base URL de la API de AudioMind.
 *
 * NEXT_PUBLIC_* se inlinea en build: en Vercel hay que definir
 * NEXT_PUBLIC_API_URL apuntando al backend desplegado
 * (ej. https://waveai-orchestrator.waveiamusic.workers.dev/api, el backend en
 * Cloudflare). La normalización de abajo
 * corrige los errores de configuración típicos y agrega el sufijo `/api`
 * cuando falta — el backend monta TODOS los routers bajo ese prefix.
 *
 * CONTRATO DE PRODUCCIÓN: en producción (NODE_ENV=production) NO existe
 * fallback a localhost. Si la variable falta, el módulo falla ruidoso en
 * build/deploy en lugar de pegarle en silencio a `localhost:8000` — el
 * bundle desplegado debe llevar SIEMPRE la URL real inlineada.
 */
const DEV_API_BASE = "http://localhost:8000/api";

function resolveRawApiBase(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured;
  if (process.env.NODE_ENV !== "production") return DEV_API_BASE;
  throw new Error(
    "[config] NEXT_PUBLIC_API_URL no está definida. Configurala en Vercel " +
      "(Settings → Environment Variables) apuntando a https://<backend>/api y redeployá.",
  );
}

/**
 * Normaliza la base contra errores de configuración típicos:
 * - trailing slash sobrante: `.../api/` -> `.../api`
 * - `/api` faltante: `https://<host>` -> `https://<host>/api`
 * - `/api` duplicado: `.../api/api` -> `.../api`
 */
function normalizeApiBase(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  const deduped = trimmed.replace(/(?:\/api){2,}(?=\/|$)/i, "/api");
  return /\/api$/i.test(deduped) ? deduped : `${deduped}/api`;
}

export const API_BASE = normalizeApiBase(resolveRawApiBase());