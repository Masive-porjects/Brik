"use client";

import { useMemo, useState, useCallback } from "react";
import {
  DEFAULT_FEATURES,
  type FeatureKey,
  type FeatureDefinition,
} from "@/shared/config/features.config";
import type { DockModuleDef } from "@/presentation/components/dock/types";

const FEATURES_STORAGE_KEY = "waveai-feature-flags";

function getInitialFeatures(): Record<FeatureKey, FeatureDefinition> {
  if (typeof window === "undefined") return DEFAULT_FEATURES;
  try {
    const saved = localStorage.getItem(FEATURES_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved) as Record<string, boolean>;
      const updated = { ...DEFAULT_FEATURES };
      for (const [key, enabled] of Object.entries(parsed)) {
        if (key in updated) {
          updated[key as FeatureKey] = {
            ...updated[key as FeatureKey],
            enabled: Boolean(enabled),
          };
        }
      }
      return updated;
    }
  } catch {
    // Ignorar modo privado
  }
  return DEFAULT_FEATURES;
}

export function useFeatures() {
  const [features, setFeatures] = useState<Record<FeatureKey, FeatureDefinition>>(getInitialFeatures);

  const isFeatureEnabled = useCallback(
    (key: FeatureKey): boolean => {
      return features[key]?.enabled ?? false;
    },
    [features],
  );

  const toggleFeature = useCallback(
    (key: FeatureKey, forcedState?: boolean) => {
      setFeatures((prev) => {
        const current = prev[key];
        if (!current) return prev;
        const nextState = forcedState ?? !current.enabled;
        const next = {
          ...prev,
          [key]: { ...current, enabled: nextState },
        };
        try {
          const overrides: Record<string, boolean> = {};
          for (const [k, v] of Object.entries(next)) {
            if (v.enabled !== DEFAULT_FEATURES[k as FeatureKey]?.enabled) {
              overrides[k] = v.enabled;
            }
          }
          localStorage.setItem(FEATURES_STORAGE_KEY, JSON.stringify(overrides));
        } catch {
          // Ignorar modo privado
        }
        return next;
      });
    },
    [],
  );

  /**
   * Filtra la lista de módulos del dock devolviendo únicamente los que tienen enabled: true
   */
  const filterDockModules = useCallback(
    <T extends DockModuleDef>(modules: readonly T[]): T[] => {
      return modules.filter((m) => isFeatureEnabled(m.key));
    },
    [isFeatureEnabled],
  );

  const enabledTabs = useMemo(() => {
    return Object.values(features)
      .filter((f) => f.enabled)
      .map((f) => f.id);
  }, [features]);

  return {
    features,
    isFeatureEnabled,
    toggleFeature,
    filterDockModules,
    enabledTabs,
  };
}
