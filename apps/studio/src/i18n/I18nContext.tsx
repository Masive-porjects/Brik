"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import esDict from "./locales/es.json";
import enDict from "./locales/en.json";

export type Locale = "es" | "en";

type Dictionary = typeof esDict;

const dictionaries: Record<Locale, Dictionary> = {
  es: esDict,
  en: enDict,
};

export const STORAGE_KEY_LANG = "waveai-lang";

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
  // Always initialize with 'es' to guarantee matching SSR and initial client hydration
  const [locale, setLocaleState] = useState<Locale>("es");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY_LANG) as Locale | null;
      if (saved && (saved === "es" || saved === "en")) {
        setLocaleState(saved);
      } else if (typeof navigator !== "undefined") {
        const browserLang = navigator.language.startsWith("es") ? "es" : "en";
        setLocaleState(browserLang);
      }
    } catch {
      // Ignorar bloqueos de privacidad
    }
  }, []);

  useEffect(() => {
    try {
      document.documentElement.lang = locale;
    } catch {
      // Ignorar entorno no-DOM
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
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
