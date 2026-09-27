"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { Play, Pause, ChevronDown, ChevronUp, SkipBack } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import gsap from "gsap";
import WaveSurfer from "wavesurfer.js";

import AudioSpectrum from "@/presentation/components/AudioSpectrum";
import { PRESET_COLORS, DEFAULT_PRESET_COLOR } from "@/core/presets";
import { renderReference, getReferenceAudioUrl } from "@/lib/api";
import { useCrossfade } from "@/shared/useCrossfade";
import { useTranslation } from "@/i18n";

/** Listening sources for the fair A/B (Original / Referencia / Master). */
type SourceKind = "original" | "reference" | "mastered";

import { PRESET_INFO } from "@/core/presets";

const PRESET_NAMES: Record<string, string> = {
  universal: "Pulido",
  fuego: "Brutal",
  claridad: "Cristalino",
  cinta: "Vintage",
  natural: "Crudo",
  espacial: "Envolvente",
  cinematico: "Épico",
  empuje: "Muro",
  calidez: "Cálido",
  espacio: "Espacial",
  club: "Club / EDM",
  dinamico: "Dinámico",
};

interface PlayerProps {
  originalUrl: string | null;
  masteredUrl: string | null;
  disabled?: boolean;
  presetId?: string;
  /** Session id — enables the on-demand Crudo reference render */
  sessionId?: string;
  /** External signal: every increment fires a note burst over the waves */
  burstSignal?: number;
}

function createWS(
  container: HTMLDivElement,
  url: string,
  waveColor: string,
  progressColor: string,
): WaveSurfer {
  const ws = WaveSurfer.create({
    container,
    waveColor,
    progressColor,
    cursorColor: "transparent",
    cursorWidth: 0,
    interact: true,
    barWidth: 2,
    barGap: 1,
    barRadius: 1,
    height: 48,
    normalize: true,
  });

  // Swallow AbortError from rapid remount
  const p = ws.load(url);
  if (p && typeof p.catch === "function") {
    p.catch(() => {});
  }

  return ws;
}

function destroyWS(ws: WaveSurfer | null) {
  if (!ws) return;
  try {
    ws.unAll();
    ws.pause();
    ws.destroy();
  } catch {
    // Swallow AbortError or double-destroy
  }
}

/* ── Waveform "wake-up" reveal ─────────────────────────
   When a WaveSurfer instance finishes loading, the bars grow
   from a compressed state instead of popping in. The two layers
   (original / mastered) reveal with a small delay so the effect
   reads as a subtle stagger. Transform-only: React keeps control
   of opacity for the A/B toggle. */
function revealWave(
  el: HTMLDivElement | null,
  delay = 0,
): gsap.core.Tween | null {
  if (!el || typeof window === "undefined") return null;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return null;
  }
  return gsap.fromTo(
    el,
    { scaleY: 0.35 },
    {
      scaleY: 1,
      duration: 0.8,
      ease: "power2.out",
      delay,
      transformOrigin: "50% 50%",
    },
  );
}

/* ── Music note burst when audio finishes loading ────── */

const NOTE_COLORS = ["#ff5a5f", "#ffb347", "#4ecdc4", "#7b68ee", "#ff6b9d"];

export function MusicNote({ color, size = 14 }: { color: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  );
}

/**
 * Note burst spread across ALL the audio waves: notes rise from
 * different positions along the full waveform width so the effect
 * covers the whole visual.
 */
function NoteBurst({ burst }: { burst: number }) {
  return (
    <AnimatePresence>
      {burst > 0 && (
        <motion.div
          key={burst}
          className="pointer-events-none absolute inset-0 overflow-hidden"
          aria-hidden="true"
        >
          {Array.from({ length: 12 }, (_, i) => {
            const x = 5 + ((i * 89 + (burst % 7) * 13) % 90);
            const delay = i * 0.05 + ((burst * 3) % 10) / 100;
            const dur = 1.1 + ((i * 13 + burst) % 7) / 10;
            const drift = ((i * 37 + burst * 7) % 80) - 40;
            const color = NOTE_COLORS[(i + burst) % NOTE_COLORS.length];
            return (
              <motion.span
                key={i}
                className="absolute"
                style={{ left: `${x}%`, bottom: 10 }}
                initial={{ y: 0, opacity: 0, scale: 0.3, rotate: -24 }}
                animate={{ y: -150, opacity: [0, 1, 1, 0], scale: 1.2, x: drift, rotate: 28 }}
                transition={{ duration: dur, delay, ease: "easeOut" }}
              >
                <MusicNote color={color} />
              </motion.span>
            );
          })}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function Player({
  originalUrl,
  masteredUrl,
  disabled,
  presetId,
  sessionId,
  burstSignal,
}: PlayerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayOrigRef = useRef<HTMLDivElement>(null);
  const overlayMastRef = useRef<HTMLDivElement>(null);
  const overlayRefPtr = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const seekOverlayRef = useRef<HTMLDivElement>(null);
  const wsOrigRef = useRef<WaveSurfer | null>(null);
  const wsMastRef = useRef<WaveSurfer | null>(null);
  const wsRefPtr = useRef<WaveSurfer | null>(null);
  const revealTweensRef = useRef<gsap.core.Tween[]>([]);

  const [isPlaying, setIsPlaying] = useState(false);
  const [source, setSource] = useState<SourceKind>("original");
  const [referenceUrl, setReferenceUrl] = useState<string | null>(null);
  const [renderingReference, setRenderingReference] = useState(false);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [noteBurst, setNoteBurst] = useState(0);
  const [minimized, setMinimized] = useState(false);
  const [playingNotes, setPlayingNotes] = useState<
    Array<{ id: number; left: number; color: string }>
  >([]);

  const isCleaningRef = useRef(false);
  const syncGuardRef = useRef(false);
  const lastEmitRef = useRef(0);
  const noteIdRef = useRef(0);
  // Mirror of `source` for event handlers created before a toggle
  // (WaveSurfer callbacks close over this ref, not stale state).
  const sourceRef = useRef<SourceKind>("original");
  // Instance that was active before the last source switch — used to
  // hand off position/playback state on toggle.
  const lastActiveWsRef = useRef<WaveSurfer | null>(null);
  const prevSourceRef = useRef<SourceKind>(source);

  // Crossfade engine — 10ms smooth transition on A/B toggle
  const { crossfade } = useCrossfade();

  useEffect(() => {
    sourceRef.current = source;
  }, [source]);

  /* ── GSAP crossfade slide between waveform sources ─────
     When Original/Master/Reference changes, the outgoing wave
     slides out and the incoming one slides in with opacity. */
  useEffect(() => {
    const from = prevSourceRef.current;
    const to = source;
    prevSourceRef.current = to;

    const getEl = (s: SourceKind) =>
      s === "mastered"
        ? overlayMastRef.current
        : s === "reference"
          ? overlayRefPtr.current
          : overlayOrigRef.current;

    const toEl = getEl(to);
    if (!toEl) return;

    [overlayOrigRef.current, overlayMastRef.current, overlayRefPtr.current].forEach((el) => {
      if (el && el !== toEl) gsap.set(el, { opacity: 0, y: -12 });
    });

    if (from !== to) {
      const fromEl = getEl(from);

      if (fromEl) {
        gsap.fromTo(
          fromEl,
          { opacity: 1, y: 0 },
          { opacity: 0, y: -18, duration: 0.45, ease: "power2.in" },
        );
      }
      gsap.fromTo(
        toEl,
        { opacity: 0, y: 18 },
        { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" },
      );
    } else {
      gsap.set(toEl, { opacity: 1, y: 0 });
    }
  }, [source]);

  const wasPlayingBeforeProcessRef = useRef(false);
  const prevMasteredUrlRef = useRef<string | null>(masteredUrl);

  // Point 3: If audio is currently playing and a mix/process is triggered (disabled becomes true),
  // pause playback immediately and flag for restart.
  useEffect(() => {
    if (disabled) {
      if (isPlaying) {
        wasPlayingBeforeProcessRef.current = true;
        wsOrigRef.current?.pause();
        wsMastRef.current?.pause();
        wsRefPtr.current?.pause();
        setIsPlaying(false);
      }
    }
  }, [disabled, isPlaying]);

  // Point 2: When a new masteredUrl is received, switch source to mastered automatically
  useEffect(() => {
    if (masteredUrl && masteredUrl !== prevMasteredUrlRef.current) {
      prevMasteredUrlRef.current = masteredUrl;
      setSource("mastered");
      sourceRef.current = "mastered";
    }
  }, [masteredUrl]);

  const hasBoth = !!(originalUrl && masteredUrl);

  /* ── Derive colors from presetId ────────────────── */
  const colors =
    PRESET_COLORS[presetId ?? ""] ?? DEFAULT_PRESET_COLOR;
  // Neutral gray for Original AND Referencia (the unprocessed sides)
  const origColors = { wave: "#484855", progress: "#666677" };

  /* ── Active instance lookup by listening source ─── */
  const wsFor = useCallback(
    (kind: SourceKind): WaveSurfer | null =>
      kind === "mastered"
        ? wsMastRef.current
        : kind === "reference"
          ? wsRefPtr.current
          : wsOrigRef.current,
    [],
  );

  /**
   * El <audio> que WaveSurfer creo para la fuente activa.
   *
   * Se guarda en estado y no en un ref porque el espectro tiene que volver a
   * montarse cuando cambia: un ref no dispara render.
   */
  const [mediaEl, setMediaEl] = useState<HTMLMediaElement | null>(null);
  useEffect(() => {
    const ws = wsFor(source);
    const el = ws
      ? (ws as unknown as { getMediaElement?: () => HTMLMediaElement }).getMediaElement?.()
      : null;
    setMediaEl(el ?? null);
  }, [source, wsFor, isPlaying]);

  /* ── Create / destroy instances on URL change ───── */
  useEffect(() => {
    isCleaningRef.current = false;

    destroyWS(wsOrigRef.current);
    destroyWS(wsMastRef.current);
    wsOrigRef.current = null;
    wsMastRef.current = null;

    const resetTimer = setTimeout(() => {
      setIsPlaying(false);
      setCurrentTime(0);
      setDuration(0);
      setPlayingNotes([]);
      lastEmitRef.current = 0;
    }, 0);

    if (!containerRef.current || !originalUrl) return;

    let loadedCount = 0;

    // ── Original instance ──────────────────────────
    const origContainer = overlayOrigRef.current;
    if (!origContainer) return;

    const orig = createWS(
      origContainer,
      originalUrl,
      origColors.wave,
      origColors.progress,
    );
    wsOrigRef.current = orig;

    const onOrigReady = () => {
      if (isCleaningRef.current) return;
      loadedCount++;
      if (loadedCount === (hasBoth ? 2 : 1)) {
        setDuration(orig.getDuration());
        setNoteBurst((n) => n + 1);
      }
      const tw = revealWave(overlayOrigRef.current);
      if (tw) revealTweensRef.current.push(tw);
    };

    const onOrigTime = (t: number) => {
      if (isCleaningRef.current) return;
      setCurrentTime(t);
      // Active instance drives every inactive one
      if (sourceRef.current === "original" && !syncGuardRef.current) {
        syncGuardRef.current = true;
        wsMastRef.current?.setTime(t);
        wsRefPtr.current?.setTime(t);
        syncGuardRef.current = false;
      }
    };

    orig.on("ready", onOrigReady);
    orig.on("timeupdate", onOrigTime);
    orig.on("play", () => {
      if (!isCleaningRef.current) setIsPlaying(true);
    });
    orig.on("pause", () => {
      if (!isCleaningRef.current) setIsPlaying(false);
    });
    orig.on("finish", () => {
      if (!isCleaningRef.current) setIsPlaying(false);
    });

    // ── Mastered instance (only when both URLs) ────
    if (hasBoth && masteredUrl && overlayMastRef.current) {
      const mast = createWS(
        overlayMastRef.current,
        masteredUrl,
        colors.wave,
        colors.progress,
      );
      wsMastRef.current = mast;

      const onMastReady = () => {
        if (isCleaningRef.current) return;
        loadedCount++;
        if (loadedCount === 2) {
          setDuration(mast.getDuration());
          setNoteBurst((n) => n + 1);
        }
        const tw = revealWave(overlayMastRef.current, 0.12);
        if (tw) revealTweensRef.current.push(tw);

        // Point 2: Automatically switch to Master tab upon new mix/master
        setSource("mastered");
        sourceRef.current = "mastered";

        // Point 3: Reiniciar la pista (reset time to 0)
        mast.seekTo(0);
        wsOrigRef.current?.seekTo(0);
        wsRefPtr.current?.seekTo(0);
        setCurrentTime(0);

        // Point 3: If it was playing when mixing started, restart playback from beginning
        if (wasPlayingBeforeProcessRef.current) {
          wasPlayingBeforeProcessRef.current = false;
          setTimeout(() => {
            if (!isCleaningRef.current) {
              mast.play().catch(() => {});
              setIsPlaying(true);
            }
          }, 200);
        }
      };

      const onMastTime = (t: number) => {
        if (isCleaningRef.current) return;
        setCurrentTime(t);
        if (sourceRef.current === "mastered" && !syncGuardRef.current) {
          syncGuardRef.current = true;
          wsOrigRef.current?.setTime(t);
          wsRefPtr.current?.setTime(t);
          syncGuardRef.current = false;
        }
      };

      mast.on("ready", onMastReady);
      mast.on("timeupdate", onMastTime);
      mast.on("play", () => {
        if (!isCleaningRef.current) setIsPlaying(true);
      });
      mast.on("pause", () => {
        if (!isCleaningRef.current) setIsPlaying(false);
      });
      mast.on("finish", () => {
        if (!isCleaningRef.current) setIsPlaying(false);
      });
    }

    return () => {
      clearTimeout(resetTimer);
      isCleaningRef.current = true;
      revealTweensRef.current.forEach((t) => t.kill());
      revealTweensRef.current = [];
      destroyWS(wsOrigRef.current);
      destroyWS(wsMastRef.current);
      wsOrigRef.current = null;
      wsMastRef.current = null;
    };
    // Intentionally run only on URL change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originalUrl, masteredUrl, hasBoth]);

  /* ── Update waveform colors when preset changes ─── */
  useEffect(() => {
    const c = PRESET_COLORS[presetId ?? ""] ?? DEFAULT_PRESET_COLOR;

    // Update mastered waveform colors
    wsMastRef.current?.setOptions({
      waveColor: c.wave,
      progressColor: c.progress,
    });

    // Update glow behind mastered waveform
    if (glowRef.current) {
      const rgba = hexToRgba(c.wave, 0.06);
      glowRef.current.style.background = `radial-gradient(ellipse at 50% 50%, ${rgba} 0%, transparent 70%)`;
    }
  }, [presetId]);

  /* ── Create / destroy the reference instance on URL change ── */
  useEffect(() => {
    if (!referenceUrl || !overlayRefPtr.current) return;

    const ref = createWS(
      overlayRefPtr.current,
      referenceUrl,
      origColors.wave,
      origColors.progress,
    );
    wsRefPtr.current = ref;

    const onRefReady = () => {
      if (isCleaningRef.current) return;
      setDuration(ref.getDuration());
      setNoteBurst((n) => n + 1);
      const tw = revealWave(overlayRefPtr.current);
      if (tw) revealTweensRef.current.push(tw);
    };

    const onRefTime = (t: number) => {
      if (isCleaningRef.current) return;
      setCurrentTime(t);
      if (sourceRef.current === "reference" && !syncGuardRef.current) {
        syncGuardRef.current = true;
        wsOrigRef.current?.setTime(t);
        wsMastRef.current?.setTime(t);
        syncGuardRef.current = false;
      }
    };

    ref.on("ready", onRefReady);
    ref.on("timeupdate", onRefTime);
    ref.on("play", () => {
      if (!isCleaningRef.current) setIsPlaying(true);
    });
    ref.on("pause", () => {
      if (!isCleaningRef.current) setIsPlaying(false);
    });
    ref.on("finish", () => {
      if (!isCleaningRef.current) setIsPlaying(false);
    });

    return () => {
      destroyWS(wsRefPtr.current);
      wsRefPtr.current = null;
    };
    // Intentionally run only on reference URL change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [referenceUrl]);

  /* ── New preset or session → old reference no longer matches ──
     The reference is loudness-matched to the ACTIVE preset, so any
     preset change invalidates it and forces a fresh render. */
  useEffect(() => {
    // Deferred out of the effect's synchronous body so we don't
    // cascade renders (react-hooks/set-state-in-effect).
    const t = setTimeout(() => {
      setReferenceUrl(null);
      setReferenceError(null);
      setSource((s) => (s === "reference" ? "original" : s));
    }, 0);
    return () => clearTimeout(t);
  }, [presetId, sessionId]);

  /* ── External burst trigger (e.g. mastering just finished) ── */
  // Derived burst key: every increment of either the internal ready
  // signal or the external signal re-fires the note burst over the waves.
  const burstKey = noteBurst + (burstSignal ?? 0);

  /* ── Crossfade on toggle (smooth A/B swap) ─────────── */
  useEffect(() => {
    const nextWs = wsFor(source);
    // Ignore an instance destroyed by a URL-change recreation
    const liveInstances = new Set([
      wsOrigRef.current,
      wsMastRef.current,
      wsRefPtr.current,
    ]);
    const prevWs = lastActiveWsRef.current;

    // Crossfade from previous to next (10ms, no clicks)
    if (prevWs && nextWs && prevWs !== nextWs && liveInstances.has(prevWs)) {
      crossfade(prevWs, nextWs);
    }
    lastActiveWsRef.current = nextWs;
  }, [source, wsFor, crossfade]);

  /* ── WaveSurfer compression on minimize/expand ───────────
     Minimizing squeezes the strip to a slim bar AND redraws
     the bars at the matching height so they compress instead
     of clipping (WaveSurfer caches its canvas size). ──────── */
  useEffect(() => {
    const h = minimized ? 16 : 48;
    (wsOrigRef.current as WaveSurfer & { setHeight?: (v: number) => void })?.setHeight?.(h);
    (wsMastRef.current as WaveSurfer & { setHeight?: (v: number) => void })?.setHeight?.(h);
    (wsRefPtr.current as WaveSurfer & { setHeight?: (v: number) => void })?.setHeight?.(h);
  }, [minimized]);

  /* ── Progressive note emission during playback ────────
     Taps the active WaveSurfer's native `timeupdate` and,
     roughly every 1.2s of *playback* time, emits a single
     MusicNote that floats up from the waveform and fades.
     Scrubbing is ignored because the handler is only
     registered while `isPlaying` is true. ────────────── */
  useEffect(() => {
    if (!isPlaying) return;

    lastEmitRef.current = 0;
    const emitGuardRef = { active: true };
    const ws = wsFor(source);
    if (!ws) return;

    const onTimeUpdate = (time: number) => {
      if (!emitGuardRef.active) return;
      if (time - lastEmitRef.current >= 1.2) {
        lastEmitRef.current = time;
        const id = noteIdRef.current++;
        const left = 5 + Math.random() * 85;
        const color =
          NOTE_COLORS[Math.floor(Math.random() * NOTE_COLORS.length)];
        setPlayingNotes((prev) =>
          [...prev.slice(-24), { id, left, color }],
        );
        // Drop the note from state after its float animation so the
        // array never grows unbounded and exit animations can play.
        setTimeout(() => {
          setPlayingNotes((prev) => prev.filter((n) => n.id !== id));
        }, 1500);
      }
    };

    ws.on("timeupdate", onTimeUpdate);
    return () => {
      // WaveSurfer's TS types don't expose `off`; flip a guard so the
      // stale listener becomes a no-op. ws.unAll() would wipe the
      // ready/play/pause listeners too.
      emitGuardRef.active = false;
    };
  }, [isPlaying, source, wsFor]);

  /* ── A/B/C handlers ─────────────────────────────── */
  const handleToggleOriginal = useCallback(() => setSource("original"), []);
  const handleToggleMastered = useCallback(() => setSource("mastered"), []);

  /* ── Crudo reference render (first selection triggers it) ── */
  const _handleToggleReference = useCallback(() => {
    setSource("reference");
    if (!sessionId || !presetId || referenceUrl || renderingReference) return;

    setRenderingReference(true);
    setReferenceError(null);
    renderReference(sessionId, presetId)
      .then(() => {
        setReferenceUrl(getReferenceAudioUrl(sessionId, presetId));
      })
      .catch(() => {
        setSource((s) => (s === "reference" ? "original" : s));
        setReferenceError(t("player.referenceError", "No se pudo generar la referencia. Prueba de nuevo."));
      })
      .finally(() => {
        setRenderingReference(false);
      });
  }, [sessionId, presetId, referenceUrl, renderingReference, t]);

  /* ── Transport ───────────────────────────────────── */
  const togglePlay = useCallback(() => {
    wsFor(source)?.playPause();
  }, [source, wsFor]);

  /* Back-to-start: rewind every stacked instance so the
     A/B/C sources stay position-synced at zero. */
  const handleRestart = useCallback(() => {
    wsOrigRef.current?.setTime(0);
    wsMastRef.current?.setTime(0);
    wsRefPtr.current?.setTime(0);
    setCurrentTime(0);
  }, []);

  /* Click or drag anywhere on the waveform to move the playhead. */
  const applySeek = useCallback(
    (clientX: number) => {
      const rect = seekOverlayRef.current?.getBoundingClientRect();
      if (!rect || duration <= 0) return;
      const percent = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const time = percent * duration;
      wsOrigRef.current?.setTime(time);
      wsMastRef.current?.setTime(time);
      wsRefPtr.current?.setTime(time);
      setCurrentTime(time);
    },
    [duration],
  );

  const handleSeekClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      applySeek(e.clientX);
    },
    [applySeek],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (duration <= 0) return;
      setIsDragging(true);
      (e.target as Element).setPointerCapture(e.pointerId);
      applySeek(e.clientX);
    },
    [applySeek, duration],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!isDragging) return;
      applySeek(e.clientX);
    },
    [applySeek, isDragging],
  );

  const handlePointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    setIsDragging(false);
    (e.target as Element).releasePointerCapture(e.pointerId);
  }, []);

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  /* ── Render ──────────────────────────────────────── */
  const activeUrl =
    source === "mastered"
      ? masteredUrl
      : source === "reference"
        ? referenceUrl
        : originalUrl;

  const sourceIndex: Record<SourceKind, number> = {
    original: 0,
    mastered: 1,
    reference: 0,
  };

  const activePresetName = presetId
    ? PRESET_INFO[presetId]?.title || PRESET_NAMES[presetId] || presetId
    : null;

  return (
    <div className="rounded-2xl py-2 px-3 overflow-hidden bg-transparent border-none">
      {/* A/B/C Toggle */}
      <div className="flex items-center justify-center gap-3 mb-2">
        <div className="relative grid grid-cols-2 bg-[var(--surface-hover)] rounded-full p-0.5 w-full max-w-[280px] sm:min-w-[240px]">
          <div
            className="absolute top-0.5 bottom-0.5 left-0 rounded-full shadow-[0_0_10px_var(--accent-primary)]/40"
            style={{
              width: "calc((100% - 4px) / 2)",
              background: "var(--accent-primary)",
              opacity: 0.25,
              transform: `translateX(calc(${sourceIndex[source] * 100}% + 2px))`,
              transition: "transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)",
            }}
          />
          <button
            onClick={handleToggleOriginal}
            disabled={disabled || !originalUrl}
            className={`relative z-10 px-2 py-1 rounded-full text-xs font-medium text-center transition-colors duration-200 flex items-center justify-center gap-1 ${
              source === "original"
                ? "text-[var(--accent-primary)] font-semibold"
                : "text-[var(--text-muted)]"
            } disabled:opacity-30 disabled:cursor-not-allowed`}
          >
            <span>{t("player.original", "Original")}</span>
            {source === "original" && (
              <span className="inline-flex items-center gap-1 ml-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-success)] shadow-[0_0_5px_var(--accent-success)]" />
                <span className="text-[9px] font-medium tracking-tight">
                  {t("player.raw", "Raw")}
                </span>
              </span>
            )}
          </button>
          <button
            onClick={handleToggleMastered}
            disabled={disabled || !masteredUrl}
            className={`relative z-10 px-2 py-1 rounded-full text-xs font-medium text-center transition-colors duration-200 flex items-center justify-center gap-1 ${
              source === "mastered"
                ? "text-[var(--accent-primary)] font-bold"
                : "text-[var(--text-muted)]"
            } disabled:opacity-30 disabled:cursor-not-allowed`}
          >
            <span>{t("player.master", "Master")}</span>
            {activePresetName && (
              <span className="text-[10px] font-semibold opacity-90 truncate max-w-[85px]">
                • {activePresetName}
              </span>
            )}
            {source === "mastered" && (
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)] shadow-[0_0_5px_var(--accent-primary)] animate-pulse" />
            )}
          </button>
        </div>

        {hasBoth && (
          <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">{t("player.instantSwitch", "Cambio instantáneo")}</span>
        )}
      </div>

      {/* Reference hint / status line */}
      {(renderingReference || referenceError || source === "reference") && (
        <p
          className={`text-[10px] mb-1 ${
            referenceError
              ? "text-[var(--accent-error)]"
              : "text-[var(--text-muted)]"
          }`}
        >
          {renderingReference
            ? t("player.generatingReference", "Generando referencia…")
            : referenceError
              ? referenceError
              : t("player.fairReferenceHint", "Mismo volumen que tu master — compará el carácter, no la fuerza.")}
        </p>
      )}

      {/* Waveform area (stacked) — minimizing compacts it to a slim strip
          (dimmed to 30%); playback keeps emitting floating notes so the
          collapsed player stays alive. */}
      <div
        className="relative transition-all duration-300 ease-out"
        style={{ height: minimized ? 20 : 48 }}
      >
        <div
          className={
            minimized
              ? "absolute inset-0 opacity-30 pointer-events-none transition-opacity duration-300"
              : "absolute inset-0 opacity-100 transition-opacity duration-300"
          }
        >
          {/* Neon glow behind mastered waveform */}
          {hasBoth && (
            <div
              ref={glowRef}
              className="absolute inset-0 transition-opacity duration-300 pointer-events-none"
              style={{
                opacity: source === "mastered" ? 1 : 0,
              }}
            />
          )}

          {/* Background container for WaveSurfer sizing */}
          <div
            ref={containerRef}
            className="absolute inset-0 opacity-0 pointer-events-none"
          />

          {/* Original waveform — always neutral gray, never tinted by the
              accent or the active preset. Color belongs to the mastered
              side of the A/B. */}
          <div
            ref={overlayOrigRef}
            className="absolute inset-0"
            style={{ filter: "none" }}
          />

          {/* Mastered waveform */}
          {hasBoth && (
            <div
              ref={overlayMastRef}
              className="absolute inset-0"
              style={{
                filter: isPlaying && source === "mastered" ? "drop-shadow(0 0 14px var(--accent-primary)) saturate(1.15)" : "none",
              }}
            />
          )}

          {/* Reference waveform (neutral gray) */}
          <div
            ref={overlayRefPtr}
            className="absolute inset-0"
            style={{
              filter: isPlaying && source === "reference" ? "drop-shadow(0 0 10px rgba(255,255,255,0.5)) saturate(1.1)" : "none",
            }}
          />

          {/* Animated playhead with glow — gray over the unprocessed
              sides (Original / Referencia); accent only on the master. */}
          {duration > 0 && (
            <div
              className="absolute top-0 bottom-0 w-0.5 z-[40] pointer-events-none"
              style={{
                left: `${(currentTime / duration) * 100}%`,
                transform: "translateX(-50%)",
                background:
                  source === "mastered"
                    ? "var(--accent-primary)"
                    : "#9aa3ad",
                boxShadow:
                  source === "mastered"
                    ? "0 0 10px var(--accent-primary), 0 0 20px var(--accent-primary)"
                    : "0 0 8px rgba(154,163,173,0.5)",
                transition: "left 60ms linear",
              }}
            />
          )}

          {/* Espectro real del audio, detras de la onda. */}
          <div className="absolute inset-0 z-[1] pointer-events-none opacity-60">
            <AudioSpectrum mediaElement={mediaEl} playing={isPlaying} />
          </div>

          {/* Subtle pulse when the track is playing */}
          {isPlaying && (
            <motion.div
              className="absolute inset-0 z-10 pointer-events-none"
              style={{
                background:
                  "radial-gradient(circle at center, rgba(98,126,132,0.15) 0%, transparent 70%)",
              }}
              initial={{ opacity: 0.2 }}
              animate={{ opacity: [0.2, 0.45, 0.2] }}
              transition={{
                duration: 1.6,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
          )}

          {/* Shimmer sweep over the active wave */}
          {isPlaying && (
            <motion.div
              className="absolute inset-0 z-20 pointer-events-none"
              initial={{ x: "-150%" }}
              animate={{ x: "250%" }}
              transition={{
                duration: 2.2,
                repeat: Infinity,
                ease: "linear",
              }}
              style={{
                width: "40%",
                background:
                  "linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)",
              }}
            />
          )}

          {/* Click-to-seek overlay */}
          <div
            ref={seekOverlayRef}
            className={`absolute inset-0 z-30 ${isDragging ? "cursor-grabbing" : "cursor-ew-resize"}`}
            onClick={handleSeekClick}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
          />

          {/* Music note burst on load / on external signal */}
          <NoteBurst burst={burstKey} />

          {/* Notes that float up progressively during playback */}
          <AnimatePresence>
            {playingNotes.map((note) => (
              <motion.span
                key={note.id}
                className="absolute pointer-events-none"
                style={{ left: `${note.left}%`, bottom: 12 }}
                initial={{ y: 0, opacity: 0, scale: 0.3, rotate: -15 }}
                animate={{ y: -120, opacity: [0, 1, 0], scale: 1.2, rotate: 20 }}
                exit={{ opacity: 0, scale: 0.5 }}
                transition={{ duration: 1.4, ease: "easeOut" }}
              >
                <MusicNote color={note.color} />
              </motion.span>
            ))}
          </AnimatePresence>
        </div>
      </div>

      {/* Transport */}
      <div className="flex items-center gap-3 mt-1">
        <button
          onClick={handleRestart}
          disabled={disabled || !activeUrl}
          className="w-8 h-8 flex items-center justify-center rounded-full
            text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]
            disabled:opacity-30 disabled:cursor-not-allowed
            transition-all duration-150"
          title={t("player.restart", "Volver al inicio")}
          aria-label={t("player.restart", "Volver al inicio")}
        >
          <SkipBack size={14} fill="currentColor" />
        </button>
        <button
          onClick={togglePlay}
          disabled={disabled || !activeUrl}
          className="w-8 h-8 flex items-center justify-center rounded-full
            bg-[var(--accent-primary)] text-[var(--bg-primary)]
            hover:brightness-110 active:scale-95
            disabled:opacity-30 disabled:cursor-not-allowed
            transition-all duration-150"
        >
          {isPlaying ? (
            <Pause size={14} fill="currentColor" />
          ) : (
            <Play size={14} fill="currentColor" />
          )}
        </button>

        <span className="text-xs font-mono text-[var(--text-muted)] w-10">
          {formatTime(currentTime)}
        </span>

        <div className="flex-1" />

        <span className="text-xs font-mono text-[var(--text-muted)] w-10 text-right">
          {formatTime(duration)}
        </span>

        <button
          onClick={() => setMinimized((m) => !m)}
          className="w-7 h-7 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-all"
          title={minimized ? t("player.expand", "Expandir") : t("player.collapse", "Minimizar")}
        >
          {minimized ? (
            <ChevronUp size={14} />
          ) : (
            <ChevronDown size={14} />
          )}
        </button>
      </div>
    </div>
  );
}

/* ── Utility: hex color → rgba string ─────────────────── */

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
