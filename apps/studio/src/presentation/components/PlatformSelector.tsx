"use client";

/* ── Platform loudness targets (Sprint 1b) ─────────────
   The chip group maps a streaming platform to the BS.1770
   integrated-loudness target its reference player expects.
   "Automatic" leaves target_lufs_db undefined so the engine
   keeps deriving the target from the limiter ceiling. */

import { useTranslation } from "@/i18n";

interface PlatformOption {
  id: string;
  label: string;
  targetLufs: number | undefined;
}

const PLATFORMS: PlatformOption[] = [
  { id: "automatic", label: "Automático", targetLufs: undefined },
  { id: "spotify", label: "Spotify", targetLufs: -14 },
  { id: "youtube", label: "YouTube", targetLufs: -14 },
  { id: "tidal", label: "Tidal", targetLufs: -14 },
  { id: "deezer", label: "Deezer", targetLufs: -14 },
  { id: "apple-music", label: "Apple Music", targetLufs: -16 },
  { id: "soundcloud", label: "SoundCloud", targetLufs: -14 },
];

interface PlatformSelectorProps {
  value: number | undefined; // target_lufs_db; undefined = automatic
  onChange: (targetLufs: number | undefined) => void;
}

export default function PlatformSelector({ value, onChange }: PlatformSelectorProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
          {t("delivery.loudnessTarget", "Loudness Target")}
        </span>
        <span className="text-[10px] font-mono text-[var(--text-muted)] tabular-nums">
          {value === undefined ? "auto" : `\u2212${Math.abs(value)} LUFS`}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {PLATFORMS.map((platform) => {
          const active =
            platform.targetLufs === undefined
              ? value === undefined
              : value === platform.targetLufs;

          const label =
            platform.id === "automatic"
              ? t("delivery.automatic", "Automático")
              : platform.label;

          return (
            <button
              key={platform.id}
              type="button"
              onClick={() => onChange(platform.targetLufs)}
              title={
                platform.targetLufs === undefined
                  ? "Recommended default"
                  : `${label} \u2212${Math.abs(platform.targetLufs)} LUFS`
              }
              className={`rounded-lg px-3 py-1.5 flex flex-col items-start gap-0.5
                transition-all duration-200 border
                ${active
                  ? "text-[var(--accent-primary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
                }`}
              style={{
                background: active
                  ? "rgba(98, 126, 132, 0.08)"
                  : "var(--surface-hover)",
                borderColor: active
                  ? "rgba(98, 126, 132, 0.25)"
                  : "var(--border-subtle)",
              }}
            >
              <span className="text-[11px] font-medium leading-none">
                {label}
              </span>
              <span
                className={`text-[9px] font-mono tabular-nums leading-none ${
                  active ? "text-[var(--accent-primary)]" : "text-[var(--text-muted)]"
                }`}
              >
                {platform.targetLufs === undefined
                  ? "auto"
                  : `\u2212${Math.abs(platform.targetLufs)} LUFS`}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
