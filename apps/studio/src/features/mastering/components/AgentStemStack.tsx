"use client";

import { motion } from "framer-motion";
import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

import { useTranslation } from "@/i18n";
import { getAudioUrl, getMixAudioUrl, getStemUrl } from "@/lib/api";
import { STEMS, type StemName } from "@/presentation/components/StemSplitter";

/**
 * Las pistas separadas, pintadas con su forma de onda REAL.
 *
 * Comportamiento:
 * - Las ondas aparecen una por una (secuencia de carga), nunca las cuatro
 *   al mismo tiempo. Evita el pico de memoria en móviles.
 * - Ninguna onda reproduce automáticamente al cargarse. El usuario decide cuándo
 *   escuchar.
 * - Dos botones al final: "Reproducir mezcla" y "Reproducir máster". Estos usan
 *   los archivos de audio completos que ya trae el job (no necesita decodificar
 *   stems en el navegador).
 * - Cada stem tiene su botón de play/pause individual para aislar esa pista si
 *   el usuario quiere escuchar una sola cosa.
 *
 * Tres decisiones intencionales:
 *
 * **Carga secuencial, no paralela.** WaveSurfer calcula la forma de onda
 * decodificando el archivo. Cuatro stems de 4 min = cientos de MB de Float32 en
 * memoria si se hacen al mismo tiempo; en móvil mata la pestaña. Cargándolas en
 * secuencia, el pico de memoria es el de un solo stem y las ondas van apareciendo
 * en orden, lo que el productor lee como "el agente mostró su trabajo paso a paso".
 *
 * **Sin auto-play al cargar.** El usuario toca un botón si quiere oír. Si la
 * onda sonara sola, el sonido se mezclaría con lo que ya estaba sonando y el
 * usuario se perdería la pista. El gesto de Moises "toque para aislar" se
 * respeta dejándolo siempre en manos del usuario.
 *
 * **Botones de mezcla y máster al final.** No intenta mezclar en el navegador
 * (sería distinto en cada dispositivo y requeriría Web Audio API compleja). En
 * su lugar, usa los archivos de audio completos que ya trae el job (mix y
 * master) y los reproduce con el `<audio>` nativo del navegador. Eso suena
 * idéntico a la entrega final y no depende de la capacidad del navegador.
 *
 * **Alto fijo, chico.** `LANE_HEIGHT = 38`. El canvas no se hace gigante en
 * mobile: el ancho escala con el contenedor, pero el alto es uno solo y compacto.
 */

const LANE_HEIGHT = 38;

/** Keep the stack ordered by the canonical track layout, not event arrival. */
export function selectVisibleStems(stemNames?: readonly StemName[]) {
  return stemNames
    ? STEMS.filter((stem) => stemNames.includes(stem.name))
    : STEMS;
}

/** `m:ss`, el formato que usa cualquier reproductor. */
function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

interface StemLaneProps {
  index: number;
  stem: (typeof STEMS)[number];
  url: string;
  /** Carga este stem en el orden secuencial (0=first, 3=last). */
  shouldLoad: boolean;
  /** Está sonando/activo este stem en este momento. */
  isActive: boolean;
  onToggle: (name: StemName) => void;
  onLoaded: (index: number) => void;
}

/** Una pista individual con su forma de onda. */
function StemLane({
  index,
  stem,
  url,
  shouldLoad,
  isActive,
  onToggle,
  onLoaded,
}: StemLaneProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const waveRef = useRef<WaveSurfer | null>(null);
  const disposedRef = useRef(false);
  const [duration, setDuration] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  const label = t(`splitter.${stem.name}`, stem.label);

  useEffect(() => {
    if (!shouldLoad) return;

    const container = containerRef.current;
    if (!container) return;

    disposedRef.current = false;

    const wave = WaveSurfer.create({
      container,
      waveColor: `${stem.color}45`,
      progressColor: stem.color,
      cursorColor: stem.color,
      cursorWidth: 0,
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
      height: LANE_HEIGHT,
      normalize: true,
      // Lectura sólo: el botón de play maneja la reproducción, arrastrar el
      // canvas no debería hacer nada audible.
      interact: false,
    });

    waveRef.current = wave;

    wave.on("ready", () => {
      if (disposedRef.current) return;
      setDuration(wave.getDuration());
      onLoaded(index);
    });

    // Un stem que ya no está en disco no rompe el panel: se marca y el resto
    // sigue cargando. Callarlo escondería un paso que la corrida sí dio.
    wave.on("error", () => {
      if (disposedRef.current) return;
      setFailed(true);
      onLoaded(index);
    });

    const loading = wave.load(url);
    if (loading && typeof loading.catch === "function") loading.catch(() => {});

    return () => {
      disposedRef.current = true;
      try {
        wave.unAll();
        wave.pause();
        wave.destroy();
      } catch {
        // Un destroy sobre un canvas ya desmontado no es un error de negocio.
      }
      waveRef.current = null;
    };
  }, [shouldLoad, url, stem.color, index, onLoaded]);

  useEffect(() => {
    const wave = waveRef.current;
    if (!wave || duration === null) return;

    // Si el usuario tiene este stem "active", lo ponemos en play/pause.
    // Si no, lo dejamos quieto (no hay auto-play).
    if (isActive) {
      const playing = wave.play();
      if (playing && typeof playing.catch === "function") playing.catch(() => {});
    } else {
      wave.pause();
    }
  }, [isActive, duration]);

  const handleClick = useCallback(() => {
    onToggle(stem.name);
  }, [onToggle, stem.name]);

  return (
    <motion.div
      animate={{
        backgroundColor: isActive ? `${stem.color}16` : "rgba(0, 0, 0, 0)",
      }}
      transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
      className="flex items-center gap-2 rounded-xl px-2 py-1.5 sm:gap-2.5 sm:px-2.5"
    >
      <motion.button
        type="button"
        onClick={handleClick}
        disabled={failed}
        whileTap={{ scale: 0.9 }}
        aria-pressed={isActive}
        aria-label={
          isActive
            ? t("productor.stemPause", { stem: label })
            : t("productor.stemPlay", { stem: label })
        }
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-opacity disabled:opacity-30"
        style={{ background: `${stem.color}1f`, color: stem.color }}
      >
        {isActive ? <Pause size={12} /> : <Play size={12} />}
      </motion.button>

      <span className="flex w-[68px] shrink-0 items-center gap-1 sm:w-[86px]">
        <stem.icon size={12} />
        <span
          className="truncate text-[11px] font-medium"
          style={{ color: isActive ? stem.color : "var(--text-secondary)" }}
        >
          {label}
        </span>
      </span>

      <div className="relative min-w-0 flex-1" style={{ height: LANE_HEIGHT }}>
        <div ref={containerRef} className="h-full w-full" />

        {duration === null && !failed && (
          <div
            className="absolute inset-0 animate-pulse rounded-md"
            style={{ background: "var(--surface-hover)" }}
            aria-hidden
          />
        )}

        {failed && (
          <p
            className="absolute inset-0 flex items-center text-[10px]"
            style={{ color: "var(--text-muted)" }}
          >
            {t("productor.stemsUnavailable")}
          </p>
        )}
      </div>

      <span
        className="hidden w-8 shrink-0 text-right text-[10px] tabular-nums sm:block"
        style={{ color: "var(--text-muted)" }}
      >
        {duration === null ? "" : formatDuration(duration)}
      </span>
    </motion.div>
  );
}

/** Pila de cuatro stems con ondas reales + botones de mezcla/máster. */
export default function AgentStemStack({
  sessionId,
  stemNames,
}: {
  sessionId: string;
  stemNames?: readonly StemName[];
}) {
  const { t } = useTranslation();
  const [active, setActive] = useState<StemName | null>(null);
  const [loadingIndex, setLoadingIndex] = useState(0);
  const visibleStems = selectVisibleStems(stemNames);

  const handleToggle = useCallback((name: StemName) => {
    setActive((current) => (current === name ? null : name));
  }, []);

  const handleLoaded = useCallback((index: number) => {
    setLoadingIndex((current) => Math.max(current, index + 1));
  }, []);

  /** Reproduce el archivo de mezcla completo (viene del job). */
  const playMix = useCallback(() => {
    const audio = new Audio(getMixAudioUrl(sessionId));
    audio.play();
  }, [sessionId]);

  /** Reproduce el archivo master completo (viene del job). */
  const playMaster = useCallback(() => {
    const audio = new Audio(getAudioUrl(sessionId, "mastered"));
    audio.play();
  }, [sessionId]);

  return (
    <div>
      <div
        className="space-y-0.5 rounded-2xl p-1.5 backdrop-blur-2xl"
        style={{
          background: "var(--bg-glass-elevated)",
          border: "1px solid var(--border-subtle)",
        }}
      >
        {visibleStems.map((stem, index) => (
          <StemLane
            key={stem.name}
            index={index}
            stem={stem}
            url={getStemUrl(sessionId, stem.name)}
            shouldLoad={index <= loadingIndex}
            isActive={active === stem.name}
            onToggle={handleToggle}
            onLoaded={handleLoaded}
          />
        ))}
      </div>

      <div className="space-y-1.5">
        <button
          onClick={playMix}
          className="w-full flex items-center justify-center rounded-md px-3 py-2 text-[10px] font-medium transition-colors hover:bg-[var(--accent-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
          aria-label={t("productor.playMix")}
        >
          <Play size={14} className="mr-2" />
          {t("productor.playMix")}
        </button>

        <button
          onClick={playMaster}
          className="w-full flex items-center justify-center rounded-md px-3 py-2 text-[10px] font-medium transition-colors hover:bg-[var(--accent-warning)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-warning)]"
          aria-label={t("productor.playMaster")}
        >
          <Pause size={14} className="mr-2" />
          {t("productor.playMaster")}
        </button>
      </div>

      <p className="mt-1.5 px-1 text-[10px]" style={{ color: "var(--text-muted)" }}>
        {t("productor.stemsHint")}
      </p>
    </div>
  );
}
