"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useSyncExternalStore,
} from "react";
import esDict from "./locales/es.json";
import enDict from "./locales/en.json";

export type Locale = "es" | "en";

type Dictionary = typeof esDict;

const dictionaries: Record<Locale, Dictionary> = {
  es: esDict,
  en: enDict,
};

export const STORAGE_KEY_LANG = "waveai-lang";

/* The preferred locale lives in localStorage, which has no store to subscribe to:
   there is no cross-tab sync, so the subscription is inert and the value is only read
   on render. `getServerSnapshot` keeps SSR deterministic ('es') and React re-renders
   with the stored value right after hydration — same timing the old mount effect had,
   without the effect writing state. */
const subscribeToLocale = () => () => {};

function readStoredLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_LANG);
    if (saved === "es" || saved === "en") return saved;
  } catch {
    // Ignorar bloqueos de privacidad
  }
  if (typeof navigator !== "undefined") {
    return navigator.language.startsWith("es") ? "es" : "en";
  }
  return "es";
}

const getServerLocale = (): Locale => "es";

interface I18nContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: (
    path: string,
    paramsOrFallback?: Record<string, string | number> | string,
    fallback?: string,
  ) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function resolvePath(obj: unknown, path: string): string | null {
  const parts = path.split(".");
  let current: unknown = obj;

  for (const part of parts) {
    if (current && typeof current === "object" && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return null;
    }
  }

  return typeof current === "string" ? current : null;
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // SSR and the initial client hydration render always use 'es'; the stored locale is
  // picked up by useSyncExternalStore on the render right after hydration.
  const storedLocale = useSyncExternalStore(subscribeToLocale, readStoredLocale, getServerLocale);
  // An explicit choice wins over what is persisted (and keeps working when storage
  // is blocked, exactly like the old state-only fallback did).
  const [localeOverride, setLocaleOverride] = useState<Locale | null>(null);
  const locale = localeOverride ?? storedLocale;

  useEffect(() => {
    try {
      document.documentElement.lang = locale;
    } catch {
      // Ignorar entorno no-DOM
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleOverride(next);
    try {
      localStorage.setItem(STORAGE_KEY_LANG, next);
      document.documentElement.lang = next;
    } catch {
      // Ignorar bloqueos de privacidad
    }
  }, []);

  const t = useCallback(
    (
      path: string,
      paramsOrFallback?: Record<string, string | number> | string,
      explicitFallback?: string,
    ): string => {
      const params =
        typeof paramsOrFallback === "object" && paramsOrFallback !== null
          ? paramsOrFallback
          : undefined;
      const fallback =
        typeof paramsOrFallback === "string" ? paramsOrFallback : explicitFallback;

      const currentDict = dictionaries[locale];
      let value = resolvePath(currentDict, path);

      // Fallback a español si no existe en el idioma activo
      if (!value && locale !== "es") {
        value = resolvePath(dictionaries.es, path);
      }

      if (!value) {
        return fallback ?? path;
      }

      if (params) {
        return Object.entries(params).reduce((acc, [key, val]) => {
          return acc.replace(new RegExp(`{${key}}`, "g"), String(val));
        }, value);
      }

      return value;
    },
    [locale],
  );

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) {
    // Fallback gracioso si se usa fuera del provider
    return {
      locale: "es",
      setLocale: () => {},
      t: (path: string) => resolvePath(dictionaries.es, path) ?? path,
    };
  }
  return context;
}
