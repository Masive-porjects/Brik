import { createStore, get, set, del } from "idb-keyval";

/**
 * Store dedicado de IndexedDB para las sesiones de mastering.
 *
 * Isolado del store por defecto de idb-keyval para que no colisione con
 * ningún otro uso futuro de la librería en la app.
 */
const sessionStore = createStore("waveai-idb", "sessions");

/** Llave bandera que marca que la migración LocalStorage → IndexedDB ya ocurrió. */
const MIGRATION_FLAG = "waveai_idb_migrated";

/** Prefijos de llaves de sesión que deben persistir en IndexedDB. */
const SESSION_KEY_PREFIXES = ["waveai-track-session-", "waveai-session", "waveai-active-session"];

/**
 * Lee un valor de la sesión persistida en IndexedDB.
 */
export async function idbGetSession<T = unknown>(key: string): Promise<T | undefined> {
  return get(key, sessionStore);
}

/**
 * Escribe un valor de sesión en IndexedDB. No bloquea la UI.
 */
export async function idbSetSession(key: string, value: unknown): Promise<void> {
  await set(key, value, sessionStore);
}

/**
 * Borra una llave de sesión de IndexedDB.
 */
export async function idbDelSession(key: string): Promise<void> {
  await del(key, sessionStore);
}

/**
 * Migración transparente y de una sola vez: copia las llaves de sesión que
 * todavía viven en LocalStorage a IndexedDB y marca la bandera para no
 * repetirla. Falla en silencio si IndexedDB no está disponible (incógnito,
 * bloqueo de cuota, etc.).
 *
 * Se llama una sola vez al montar la app. `waveai-theme` se deja en
 * LocalStorage a propósito (cambio de tema síncrono sin parpadeo).
 */
export async function idbMigrateFromLocalStorage(): Promise<void> {
  if (typeof window === "undefined" || !localStorage) return;

  try {
    const alreadyMigrated = localStorage.getItem(MIGRATION_FLAG);
    if (alreadyMigrated === "1") return;

    const keysToMigrate: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key) continue;
      if (SESSION_KEY_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        keysToMigrate.push(key);
      }
    }

    for (const key of keysToMigrate) {
      const value = localStorage.getItem(key);
      if (value !== null) {
        await idbSetSession(key, value);
      }
    }

    await idbSetSession(MIGRATION_FLAG, "1");
  } catch {
    // IndexedDB no disponible o error silencioso: seguimos con LocalStorage
    // como respaldo y la app funciona igual.
  }
}

/**
 * Lista todas las llaves de sesión guardadas en IndexedDB.
 */
export async function idbListSessionKeys(): Promise<string[]> {
  try {
    const allKeys = (await (sessionStore as unknown as { keys?: () => Promise<string[]> }).keys?.()) ?? [];
    return allKeys.filter((k) =>
      SESSION_KEY_PREFIXES.some((prefix) => k.startsWith(prefix))
    );
  } catch {
    return [];
  }
}
