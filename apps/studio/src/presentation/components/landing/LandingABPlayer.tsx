"use client";

import { useState, useEffect, useRef } from "react";
import { Play, Pause } from "lucide-react";
import { useTranslation } from "@/i18n";

export default function LandingABPlayer() {
  const { t } = useTranslation();
  const [isBrik, setIsBrik] = useState<boolean>(true);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [intensity, setIntensity] = useState<number>(70);
  const [playheadPos, setPlayheadPos] = useState<number>(33);
  const audioContextRef = useRef<AudioContext | null>(null);
  const oscillatorRef = useRef<OscillatorNode | null>(null);

  // Playhead scrubber animation
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;
    if (isPlaying) {
      interval = setInterval(() => {
        setPlayheadPos((prev) => (prev >= 95 ? 2 : prev + 0.8));
      }, 50);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isPlaying]);

  // Clean Web Audio preview tone / synthetic master groove
  const togglePlay = () => {
    if (isPlaying) {
      if (oscillatorRef.current) {
        try {
          oscillatorRef.current.stop();
          oscillatorRef.current.disconnect();
        } catch {}
        oscillatorRef.current = null;
      }
      setIsPlaying(false);
    } else {
      try {
        const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        if (!audioContextRef.current) {
          audioContextRef.current = new AudioCtx();
        }
        if (audioContextRef.current.state === "suspended") {
          audioContextRef.current.resume();
        }

        // Gentle ambient sub-bass & stereo harmonic drone
        const osc = audioContextRef.current.createOscillator();
        const gain = audioContextRef.current.createGain();
        osc.type = isBrik ? "sawtooth" : "sine";
        osc.frequency.setValueAtTime(isBrik ? 110 : 82.4, audioContextRef.current.currentTime);

        const filter = audioContextRef.current.createBiquadFilter();
        filter.type = "lowpass";
        filter.frequency.setValueAtTime(isBrik ? 2400 : 800, audioContextRef.current.currentTime);

        gain.gain.setValueAtTime(0.015 * (intensity / 100), audioContextRef.current.currentTime);

        osc.connect(filter);
        filter.connect(gain);
        gain.connect(audioContextRef.current.destination);
        osc.start();
        oscillatorRef.current = osc;
      } catch {
        // Fallback for browsers with restricted autoplay
      }
      setIsPlaying(true);
    }
  };

  useEffect(() => {
    return () => {
      if (oscillatorRef.current) {
        try {
          oscillatorRef.current.stop();
        } catch {}
      }
    };
  }, []);

  const masterPath =
    "M0,60 C40,25 80,95 120,30 C160,-10 200,110 240,60 C280,15 320,95 360,40 C400,10 440,110 480,55 C520,20 560,95 600,35 C640,-5 680,115 720,60 C760,15 800,100 840,30 C880,-5 920,105 960,60 L1000,45";
  const origPath =
    "M0,60 C40,52 80,68 120,55 C160,45 200,75 240,60 C280,50 320,70 360,58 C400,48 440,72 480,60 C520,52 560,68 600,55 C640,45 680,75 720,60 C760,52 800,68 840,55 C880,48 920,72 960,60 L1000,58";

  return (
    <section className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#121317] relative" id="comparador">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col items-center text-center gap-2 max-w-3xl mx-auto">
          <span className="font-label-technical text-secondary text-[10px] uppercase tracking-widest">
            {t("landing.abPlayer.badge", "Escucha Espectral")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
            {t("landing.abPlayer.title", "Comparador A/B: Original vs Master Brik")}
          </h2>
          <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
            {t(
              "landing.abPlayer.subtitle",
              "Experimenta la alteración psicoacústica en vivo. Alterna entre la mezcla previa y el resultado final procesado por nuestro motor de 13 etapas."
            )}
          </p>
        </div>

        {/* Interactive Audio Widget Shell */}
        <div className="w-full bg-[#1a1b20] rounded-2xl p-5 sm:p-8 lg:p-10 shadow-2xl border border-white/5 flex flex-col gap-6">
          {/* Control Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-white/10">
            {/* Track Info & Play */}
            <div className="flex items-center gap-3.5">
              <button
                type="button"
                onClick={togglePlay}
                className="w-12 h-12 rounded-full bg-primary text-[#003734] flex items-center justify-center hover:bg-primary-container transition-all shadow-[0_0_18px_rgba(110,233,224,0.35)] hover:scale-105 active:scale-95 cursor-pointer"
                aria-label={isPlaying ? "Pausar audio" : "Reproducir audio"}
              >
                {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
              </button>
              <div className="flex flex-col">
                <span className="font-headline-sm text-sm sm:text-base font-semibold text-[#e3e2e8]">
                  {t("landing.abPlayer.trackTitle", "Resonancia Espectral (Stems Master)")}
                </span>
                <span className="font-label-technical text-[10px] text-[#869391]">
                  {t("landing.abPlayer.trackMeta", "ELECTRONIC BASS MUSIC — 128 BPM — 24-BIT 48KHZ")}
                </span>
              </div>
            </div>

            {/* Slider & Switchers */}
            <div className="flex flex-wrap items-center gap-4">
              {/* DSP Intensity Slider */}
              <div className="flex items-center gap-2.5 bg-[#1f1f24] px-4 py-1.5 rounded-full border border-white/5">
                <span className="font-label-technical text-[10px] text-[#869391] uppercase">
                  {t("landing.abPlayer.intensityLabel", "INTENSIDAD DSP:")}
                </span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={intensity}
                  onChange={(e) => setIntensity(Number(e.target.value))}
                  className="accent-primary w-20 sm:w-28 h-1.5 rounded-lg cursor-pointer bg-[#343439]"
                />
                <span className="font-label-technical text-xs text-primary font-bold w-9 text-right">
                  {intensity}%
                </span>
              </div>

              {/* A/B Switch Pills */}
              <div className="flex items-center p-1 bg-[#292a2e] rounded-full border border-white/5 shadow-inner">
                <button
                  type="button"
                  onClick={() => setIsBrik(false)}
                  className={`px-4 py-1.5 rounded-full font-label-technical text-xs font-bold transition-all cursor-pointer ${
                    !isBrik
                      ? "bg-[#38393e] text-[#e3e2e8] shadow-md border border-white/10"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.abPlayer.btnOrig", "ORIGINAL [A]")}
                </button>
                <button
                  type="button"
                  onClick={() => setIsBrik(true)}
                  className={`px-4 py-1.5 rounded-full font-label-technical text-xs font-bold transition-all cursor-pointer ${
                    isBrik
                      ? "bg-primary text-[#003734] shadow-[0_0_12px_rgba(110,233,224,0.35)]"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.abPlayer.btnBrik", "MASTER BRIK [B]")}
                </button>
              </div>
            </div>
          </div>

          {/* Spectral Waveform Vector Canvas */}
          <div className="relative w-full h-52 sm:h-56 bg-[#0d0e12] rounded-xl p-4 overflow-hidden flex flex-col justify-between border border-white/5">
            <div className="flex items-center justify-between text-xs font-label-technical z-10">
              <span className="text-primary font-bold">SPECTRUM RTA: 20Hz - 22kHz</span>
              <span
                className={`uppercase tracking-wider transition-colors duration-300 ${
                  isBrik ? "text-primary" : "text-[#869391]"
                }`}
              >
                {isBrik
                  ? t("landing.abPlayer.statusBrik", "SATURACIÓN ARMÓNICA BRIK ACTIVADA (+2.8 dB AIR)")
                  : t("landing.abPlayer.statusOrig", "MEZCLA PREVIA SIN PROCESAR (PUNTAS DINÁMICAS PLANAS)")}
              </span>
            </div>

            {/* Simulated Dynamic Waveform SVG */}
            <div className="relative w-full h-32 flex items-center justify-center">
              <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 1000 120">
                <path
                  d={isBrik ? masterPath : origPath}
                  fill="none"
                  stroke={isBrik ? "rgba(110,233,224,0.3)" : "rgba(134,147,145,0.2)"}
                  strokeWidth="8"
                  className="transition-all duration-500 ease-out"
                />
                <path
                  d={isBrik ? masterPath : origPath}
                  fill="none"
                  stroke={isBrik ? "#6ee9e0" : "#869391"}
                  strokeWidth="2.5"
                  className="transition-all duration-500 ease-out"
                />
              </svg>

              {/* Scrubber Playhead */}
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-secondary shadow-[0_0_8px_#cf5cff] transition-[left] duration-75"
                style={{ left: `${playheadPos}%` }}
              />
            </div>

            {/* Frequency Ticks */}
            <div className="flex items-center justify-between text-[#869391] font-label-technical text-[10px] z-10 px-1">
              <span>20 Hz</span>
              <span>100 Hz</span>
              <span>1 kHz</span>
              <span>5 kHz</span>
              <span>12 kHz</span>
              <span>20 kHz</span>
            </div>
          </div>

          {/* Telemetry Realtime Meters Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
            <div className="p-3 sm:p-4 bg-[#1f1f24] rounded-lg border border-white/5 flex flex-col gap-1.5">
              <span className="font-label-technical text-[10px] text-[#869391]">
                {t("landing.abPlayer.meterLufs", "INTEGRATED LUFS")}
              </span>
              <div className="flex items-baseline justify-between">
                <span className="font-metric-val-lg text-lg sm:text-2xl text-primary font-bold">
                  {isBrik ? "-14.1" : "-19.4"}
                </span>
                <span className="font-label-technical text-xs text-primary">LUFS</span>
              </div>
              <div className="w-full bg-[#343439] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-primary h-full transition-all duration-500"
                  style={{ width: isBrik ? "84%" : "55%" }}
                />
              </div>
            </div>

            <div className="p-3 sm:p-4 bg-[#1f1f24] rounded-lg border border-white/5 flex flex-col gap-1.5">
              <span className="font-label-technical text-[10px] text-[#869391]">
                {t("landing.abPlayer.meterTp", "MAX TRUE PEAK")}
              </span>
              <div className="flex items-baseline justify-between">
                <span className="font-metric-val-lg text-lg sm:text-2xl text-secondary font-bold">
                  {isBrik ? "-0.98" : "-3.40"}
                </span>
                <span className="font-label-technical text-xs text-secondary">dBTP</span>
              </div>
              <div className="w-full bg-[#343439] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-secondary h-full transition-all duration-500"
                  style={{ width: isBrik ? "90%" : "62%" }}
                />
              </div>
            </div>

            <div className="p-3 sm:p-4 bg-[#1f1f24] rounded-lg border border-white/5 flex flex-col gap-1.5">
              <span className="font-label-technical text-[10px] text-[#869391]">
                {t("landing.abPlayer.meterWidth", "ESTÉREO HAAS WIDTH")}
              </span>
              <div className="flex items-baseline justify-between">
                <span className="font-metric-val-lg text-lg sm:text-2xl text-tertiary-container font-bold">
                  {isBrik ? "132%" : "98%"}
                </span>
                <span className="font-label-technical text-xs text-tertiary-container">WARP</span>
              </div>
              <div className="w-full bg-[#343439] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-tertiary-container h-full transition-all duration-500"
                  style={{ width: isBrik ? "78%" : "48%" }}
                />
              </div>
            </div>

            <div className="p-3 sm:p-4 bg-[#1f1f24] rounded-lg border border-white/5 flex flex-col gap-1.5">
              <span className="font-label-technical text-[10px] text-[#869391]">
                {t("landing.abPlayer.meterHarm", "DENSIDAD ARMÓNICA")}
              </span>
              <div className="flex items-baseline justify-between">
                <span className="font-metric-val-lg text-lg sm:text-2xl text-primary font-bold">
                  {isBrik ? "+4.2 dB" : "0.0 dB"}
                </span>
                <span className="font-label-technical text-xs text-primary">THD</span>
              </div>
              <div className="w-full bg-[#343439] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-primary h-full transition-all duration-500"
                  style={{ width: isBrik ? "65%" : "15%" }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
