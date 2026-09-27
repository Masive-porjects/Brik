"use client";

import { useI18n, type Locale } from "./I18nContext";

export function useTranslation() {
  const { t, locale, setLocale } = useI18n();

  return {
    t,
    locale,
    setLocale,
    isEs: locale === "es",
    isEn: locale === "en",
  };
}

export type { Locale };
