/**
 * Resolves the application base URL used to build auth redirect targets
 * (OAuth callbacks, email confirmation links).
 *
 * Resolution order:
 * 1. `NEXT_PUBLIC_SITE_URL` — canonical domain, e.g. https://www.brikmusic.online
 * 2. `NEXT_PUBLIC_VERCEL_URL` — Vercel preview/deployment host (no scheme)
 * 3. Current browser origin — covers previews where no env var is exposed
 * 4. `http://localhost:3000/` — local development fallback
 *
 * The result always carries a scheme and a trailing slash, so callers can
 * concatenate paths directly: `${getURL()}auth/callback`.
 */
export const getURL = () => {
  let url =
    process.env.NEXT_PUBLIC_SITE_URL ??
    process.env.NEXT_PUBLIC_VERCEL_URL ??
    (typeof window !== "undefined" ? window.location.origin : undefined) ??
    "http://localhost:3000/";

  // Vercel exposes bare hosts (no scheme); production domains must be https.
  url = url.includes("http") ? url : `https://${url}`;
  // Guarantee a trailing slash so path concatenation never produces "domainauth".
  url = url.endsWith("/") ? url : `${url}/`;
  return url;
};
