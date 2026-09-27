/**
 * LiveView — Main Live Engine container.
 * Standalone Web Audio player controlled by knobs (no camera/WS).
 */

'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLiveEngine } from '@/adapters/live/useLiveEngine';
import { safeCloseAudioContext } from '@/lib/live/audioContextUtils';
import { FxSlotPanel } from './FxSlotPanel';
import { LiveMeterDeck } from './LiveMeterDeck';
import { LiveRecorderBar } from './LiveRecorderBar';
import type { LiveSide, LiveStaticMetrics } from './PresetHeader';

interface LiveViewProps {
  /** Master audio buffer URL or blob */
  masterAudioUrl?: string | null;
  /** Master audio buffer (decoded) */
  masterAudioBuffer?: AudioBuffer | null | undefined;
  /** Whether the Live tab is active */
  isActive?: boolean;
  /** Preset activo del flujo de mastering (para preset header + target LUFS). */
  presetId?: string | null;
  /** Métricas estáticas del original (session.analysis) — campos reales de los tipos API. */
  originalMetrics?: LiveStaticMetrics | null;
  /** Métricas estáticas del master (session.master_result). */
  masterMetrics?: LiveStaticMetrics | null;
}

/** Parámetros iniciales (neutrales) del Live Engine — el hook ya inicializa con defaults del schema. */

export function LiveView({
  masterAudioUrl,
  masterAudioBuffer,
  isActive = false,
  presetId = null,
  originalMetrics = null,
  masterMetrics = null,
}: LiveViewProps) {
  // Lado del A/B estático (Original | Master) — estado lento del deck.
  const [side, setSide] = useState<LiveSide>('original');

  // ── Master real del flujo de mastering ─────────────────────────────
  // El padre pasa la URL del masterizado (getAudioUrl(session_id, "mastered")).
  // La decodificamos a AudioBuffer para el Live Engine. Con un AudioContext
  // efímero (el decode es puntual; el hook usa el suyo para el graph).
  const [masterBuffer, setMasterBuffer] = useState<AudioBuffer | null>(null);
  const [decodedUrl, setDecodedUrl] = useState<string | null>(null);

  // Patrón oficial React: si la URL cambió, descartar el buffer viejo
  // (ajuste de estado durante render, no en efecto).
  if (decodedUrl !== (masterAudioUrl ?? null)) {
    setDecodedUrl(masterAudioUrl ?? null);
    setMasterBuffer(null);
  }

  useEffect(() => {
    if (!masterAudioUrl) return;

    let cancelled = false;
    const ctx = new AudioContext();
    fetch(masterAudioUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`fetch master: HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then((buf) => ctx.decodeAudioData(buf))
      .then((audioBuf) => {
        if (!cancelled) setMasterBuffer(audioBuf);
      })
      .catch((err) => console.error('[LiveView] decode master:', err))
      .finally(() => { void safeCloseAudioContext(ctx); });

    return () => { cancelled = true; };
  }, [masterAudioUrl]);

  // Use the live engine hook
  const {
    params,
    recorderState,
    isPlaying,
    setParams,
    setFxPreset,
    play,
    pause,
    stop,
    startRecording,
    stopRecording,
    downloadRecording,
    destroy,
  } = useLiveEngine({
    masterAudioBuffer: masterBuffer ?? masterAudioBuffer ?? null,
    initialParams: {
      filter_cutoff: 12000,
      filter_res: 0.7,
      drive: 0,
      delay_time: 250,
      echo_feedback: 0,
      reverb_mix: 0,
      output_level: 0.9,
      fx_preset: null,
    },
    onParamsChange: (p) => {}, // Handled by hook internally
    onError: (err) => console.error('[LiveEngine]', err),
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => destroy();
  }, [destroy]);

  // Hay master disponible (buffer decodificado o URL pendiente de decode).
  const hasMaster = !!(masterBuffer ?? masterAudioBuffer) || !!masterAudioUrl;

  if (!isActive) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', color: '#8a8a8a', padding: 32 }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🎛️</div>
            <h2 style={{ margin: '0 0 8px', color: '#e8e8e8' }}>Live Engine</h2>
            <p style={{ margin: 0, color: '#8a8a8a' }}>
              Selecciona la pestaña Live para activar el motor de audio
            </p>
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      data-testid="live-view"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -16 }}
      style={{
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '1.2fr 1fr',
        gridTemplateRows: '1fr auto',
        gap: 16,
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Column 1: FX Chain */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          overflow: 'auto',
          padding: '0 8',
        }}
      >
        {/* Header with status */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '10px 16px',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.05)',
            borderRadius: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: '#e8e8e8' }}>LIVE ENGINE</span>
          </div>
        </div>

        {/* FX Slot Panel */}
        <FxSlotPanel
          params={params}
          onParamsChange={setParams}
          onPresetChange={setFxPreset}
        />
      </motion.div>

      {/* Column 2: Meters (recorder lives full-width below) */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.15 }}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          overflow: 'auto',
          paddingLeft: 8,
        }}
      >
        <LiveMeterDeck
          width={280}
          height={400}
          presetId={presetId}
          isPlaying={isPlaying}
          isActive={isActive}
          hasMaster={hasMaster}
          side={side}
          originalMetrics={originalMetrics}
          masterMetrics={masterMetrics}
          onSideChange={setSide}
        />
      </motion.div>

      {/* Bottom: Full-width recorder bar when active */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        style={{
          gridColumn: '1 / -1',
          maxHeight: 200,
        }}
      >
        <LiveRecorderBar
          recorderState={recorderState}
          isPlaying={isPlaying}
          onPlay={play}
          onPause={pause}
          onStop={stop}
          onStartRecording={startRecording}
          onStopRecording={stopRecording}
          onDownload={downloadRecording}
        />
      </motion.div>

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </motion.div>
  );
}