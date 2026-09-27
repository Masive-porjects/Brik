"use client";

import { useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { Clock, Headphones, AudioWaveform } from "lucide-react";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";
import DropZone from "@/presentation/components/DropZone";
import WaveformBars from "./WaveformBars";
import { useTranslation } from "@/i18n/useTranslation";
import { VIEW_TRANSITION } from "@/shared/motion";

const NOTE_COLORS = ["#ff5a5f", "#ffb347", "#4ecdc4", "#7b68ee", "#ff6b9d"];

interface UploadViewProps {
  onFileSelected: (file: File) => void;
  onError: (title: string, message: string) => void;
  loading: boolean;
  uploadBurst: number;
}

export default function UploadView({
  onFileSelected,
  onError,
  loading,
  uploadBurst,
}: UploadViewProps) {
  const { t } = useTranslation();
  const uploadCardRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (!uploadCardRef.current) return;
      gsap.to(uploadCardRef.current, {
        y: -6,
        duration: 2.6,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });
    },
    { scope: uploadCardRef },
  );

  return (
    <div className="flex-1 flex items-center justify-center px-6 py-8 overflow-y-auto relative">
      <BigGhostWithNotes className="left-1/2 -top-8" />
      <AnimatePresence mode="wait">
        <motion.div
          key="upload"
          className="w-full max-w-2xl flex flex-col items-center"
          initial={VIEW_TRANSITION.initial}
          animate={VIEW_TRANSITION.animate}
          exit={VIEW_TRANSITION.exit}
          transition={VIEW_TRANSITION.transition}
        >
          {/* Tarjeta de Cristal Elevada */}
          <div
            ref={uploadCardRef}
            className="relative w-full rounded-3xl p-4 md:p-6 text-center glass-elevated"
            style={{ boxShadow: "var(--shadow-heavy)" }}
          >
            <div className="mb-2">
              <div className="inline-flex items-center gap-2 mb-1">
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)]" />
                <span className="text-[10px] font-medium tracking-widest uppercase text-[var(--text-secondary)]">
                  WaveIA
                </span>
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-secondary)]" />
              </div>

              <h1
                className="text-2xl md:text-4xl font-bold mb-1 text-knockout"
                style={{ letterSpacing: "-0.04em" }}
              >
                {t("upload.heroPrefix", "Masteriza Tu")}{" "}
                <span className="serif-accent">{t("upload.heroAccent", "Música")}</span>
              </h1>

              <p className="text-[var(--text-muted)] text-sm">
                {t(
                  "upload.heroSubtitle",
                  "Carga tu track, ajusta los módulos y obtén un master profesional",
                )}
              </p>
            </div>

            <DropZone
              onFileSelected={onFileSelected}
              onError={onError}
              disabled={loading}
            />

            {/* Explosión de notas musicales al completar la subida */}
            {uploadBurst > 0 && (
              <div className="pointer-events-none absolute inset-0 overflow-hidden">
                {NOTE_COLORS.map((c, i) => {
                  const dx = ((i * 37 + uploadBurst * 7) % 70) - 35;
                  const delay = ((i * 29 + uploadBurst) % 20) / 100;
                  const dur = 1 + ((i * 13 + uploadBurst) % 6) / 10;
                  return (
                    <motion.span
                      key={i}
                      className="absolute"
                      style={{ left: "50%", bottom: "10px", x: dx }}
                      initial={{
                        y: 0,
                        opacity: 0,
                        scale: 0.3,
                        rotate: -20,
                      }}
                      animate={{
                        y: -140,
                        opacity: [0, 1, 1, 0],
                        scale: 1.2,
                        rotate: 24,
                      }}
                      transition={{ duration: dur, delay, ease: "easeOut" }}
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke={c}
                        strokeWidth={2.4}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M9 18V5l12-2v13" />
                        <circle cx="6" cy="18" r="3" />
                        <circle cx="18" cy="16" r="3" />
                      </svg>
                    </motion.span>
                  );
                })}
              </div>
            )}
          </div>

          {/* Píldoras de Metadatos de Audio */}
          <div className="flex flex-wrap items-center justify-center gap-3 mt-3">
            <span className="flex items-center gap-1 text-[var(--text-muted)] text-xs">
              <Clock size={12} />
              {t("upload.lufsStandard", "-14 LUFS Standard")}
            </span>
            <span className="flex items-center gap-1 text-[var(--text-muted)] text-xs">
              <Headphones size={12} />
              {t("upload.dspModules", "4 Módulos DSP")}
            </span>
            <span className="flex items-center gap-1 text-[var(--text-muted)] text-xs">
              <AudioWaveform size={12} />
              {t("upload.proQuality", "Calidad Profesional")}
            </span>
          </div>

          {/* Forma de onda decorativa interactiva */}
          <div className="mt-3 opacity-15 pointer-events-none">
            <WaveformBars isPlaying />
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
