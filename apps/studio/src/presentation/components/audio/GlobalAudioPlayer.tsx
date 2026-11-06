"use client";

import { useEffect, useRef, useCallback } from "react";
import { Play, Pause, Volume2, VolumeX, SkipBack, SkipForward } from "lucide-react";
import { useAudioPlayerStore } from "@/features/audio/store/audioPlayerStore";
import { useTranslation } from "@/i18n";

/**
 * Reproductor de audio global tipo Spotify/SoundCloud.
 *
 * Se monta en el layout raíz para que sobreviva a la navegación entre
 * rutas de Next.js. Usa un elemento <audio> nativo con una blob URL o
 * URL de descarga, sincronizado con un store de Zustand para evitar
 * re-renders innecesarios y permitir que cualquier componente dispare
 * reproducción sin perder el estado al cambiar de página.
 */
export default function GlobalAudioPlayer() {
  const {
    src,
    kind,
    title,
    playing,
    currentTime,
    duration,
    volume,
    activeStemId,
    load,
    togglePlay,
    setCurrentTime,
    setDuration,
    setVolume,
    stop,
    setActiveStem,
  } = useAudioPlayerStore((state) => state);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const isMountedRef = useRef(false);

  // Sincronizar el store con el elemento <audio> nativo.
  useEffect(() => {
    if (!audioRef.current) return;
    const audio = audioRef.current;

    if (src) {
      audio.src = src;
      audio.volume = volume;
      if (playing) {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
    } else {
      audio.pause();
      audio.src = "";
    }

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
    };
    const handleDurationChange = () => {
      setDuration(audio.duration);
    };
    const handleEnded = () => {
      // Cuando termina, detener y limpiar.
      stop();
    };
    const handlePlay = () => {
      // No-op: el store maneja el estado de playing.
    };
    const handlePause = () => {
      // No-op: el store maneja el estado de playing.
    };

    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("durationchange", handleDurationChange);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);

    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("durationchange", handleDurationChange);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
    };
  }, [src, playing, volume, setCurrentTime, setDuration, stop]);

  const handleTogglePlay = useCallback(() => {
    if (!audioRef.current) return;
    togglePlay();
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play().catch(() => {});
    }
  }, [togglePlay, playing]);

  const handleSetVolume = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const vol = parseFloat(e.target.value);
      setVolume(vol);
      if (audioRef.current) {
        audioRef.current.volume = vol;
      }
    },
    [setVolume],
  );

  const handleSeek = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const time = parseFloat(e.target.value);
      setCurrentTime(time);
      if (audioRef.current) {
        audioRef.current.currentTime = time;
      }
    },
    [setCurrentTime],
  );

  const { t } = useTranslation();

  const formatTime = (seconds: number): string => {
    if (!seconds || isNaN(seconds)) return "--:--";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  // Crear el elemento de audio una sola vez; persiste entre navegaciones.
  // Se hace en un efecto para no tocar el DOM durante el render.
  useEffect(() => {
    if (isMountedRef.current) return;
    isMountedRef.current = true;
    if (typeof window !== "undefined") {
      const el = document.createElement("audio");
      el.preload = "metadata";
      el.style.display = "none";
      document.body.appendChild(el);
      audioRef.current = el;
    }
  }, []);

  const hasAudio = !!src;

  return (
    <div
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[60] w-full max-w-[420px] rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] backdrop-blur-2xl p-3 shadow-lg"
      aria-label="Reproductor de audio global"
    >
      {/* Barra de título y controles principales */}
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <p
            className="text-xs font-medium text-[var(--text-primary)] truncate"
            title={title || t("audio.noTrack")}
          >
            {hasAudio ? title : t("audio.noTrack")}
          </p>
          <p
            className="text-[10px] text-[var(--text-muted)] truncate"
            title={kind ? `Tipo: ${kind}` : ""}
          >
            {kind ? `Tipo: ${kind}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={handleTogglePlay}
          aria-label={playing ? t("common.pause") : t("common.play")}
          className="flex items-center justify-center w-8 h-8 rounded-full bg-[var(--surface-elevated)] hover:bg-[var(--surface-active)] text-[var(--text-primary)] transition-colors"
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        {hasAudio && (
          <button
            type="button"
            onClick={() => stop()}
            aria-label={t("common.stop")}
            className="flex items-center justify-center w-8 h-8 rounded-full bg-[var(--surface-elevated)] hover:bg-red-500/20 text-red-400 hover:text-red-500 transition-colors"
          >
            <SkipForward size={14} />
          </button>
        )}
      </div>

      {/* Barra de progreso */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] text-[var(--text-muted)] w-16">
          {formatTime(currentTime)}
        </span>
        <input
          type="range"
          min="0"
          max={duration || 100}
          value={currentTime}
          onChange={handleSeek}
          className="flex-1 h-1 bg-[var(--border-subtle)] rounded-lg appearance-none cursor-pointer accent-[var(--accent-primary)]"
        />
        <span className="text-[10px] text-[var(--text-muted)] w-16">
          {formatTime(duration)}
        </span>
      </div>

      {/* Volumen */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            const newVol = volume > 0 ? 0 : 1;
            setVolume(newVol);
            if (audioRef.current) audioRef.current.volume = newVol;
          }}
          aria-label={volume > 0 ? t("common.mute") : t("common.unmute")}
          className="flex items-center justify-center w-6 h-6 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        >
          {volume > 0 ? <Volume2 size={14} /> : <VolumeX size={14} />}
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={volume}
          onChange={handleSetVolume}
          className="w-24 h-1 bg-[var(--border-subtle)] rounded-lg appearance-none cursor-pointer accent-[var(--accent-primary)]"
        />
      </div>

      {/* Indicador de stem activo */}
      {hasAudio && activeStemId && (
        <p className="text-[10px] text-[var(--accent-primary)] font-medium mt-1">
          Stem activo: {activeStemId}
        </p>
      )}
    </div>
  );
}
