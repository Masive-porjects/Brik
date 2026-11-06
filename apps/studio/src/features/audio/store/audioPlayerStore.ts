import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AudioKind = "master" | "stem";

export interface AudioPlayerState {
  /** URL del audio actualmente cargado (blob URL o URL de descarga). */
  src: string | null;
  /** Tipo de audio: "master" o "stem". */
  kind: AudioKind | null;
  /** Título del track para mostrar en el reproductor. */
  title: string;
  /** Estado de reproducción. */
  playing: boolean;
  /** Tiempo actual en segundos. */
  currentTime: number;
  /** Duración total en segundos. */
  duration: number;
  /** Volumen (0-1). */
  volume: number;
  /** ID del stem activo (si es un stem). */
  activeStemId: string | null;
}

interface AudioPlayerActions {
  /** Carga un nuevo audio y lo pone listo para reproducir. */
  load: (src: string, kind: AudioKind, title: string) => void;
  /** Reproduce o pausa el audio actual. */
  togglePlay: () => void;
  /** Establece el tiempo actual de reproducción. */
  setCurrentTime: (time: number) => void;
  /** Establece la duración del audio. */
  setDuration: (dur: number) => void;
  /** Establece el volumen. */
  setVolume: (vol: number) => void;
  /** Detiene y limpia el reproductor. */
  stop: () => void;
  /** Marca el stem activo. */
  setActiveStem: (stemId: string | null) => void;
}

type AudioPlayerStore = AudioPlayerState & AudioPlayerActions;

const initialState: AudioPlayerState = {
  src: null,
  kind: null,
  title: "",
  playing: false,
  currentTime: 0,
  duration: 0,
  volume: 1,
  activeStemId: null,
};

export const useAudioPlayerStore = create<AudioPlayerStore>()(
  persist(
    (set) => ({
      ...initialState,

      load: (src, kind, title) =>
        set({ src, kind, title, playing: true, currentTime: 0, duration: 0 }),

      togglePlay: () =>
        set((state) => ({ playing: !state.playing })),

      setCurrentTime: (time) => set({ currentTime: time }),

      setDuration: (dur) => set({ duration: dur }),

      setVolume: (vol) => set({ volume: vol }),

      stop: () =>
        set({
          src: null,
          kind: null,
          title: "",
          playing: false,
          currentTime: 0,
          duration: 0,
          activeStemId: null,
        }),

      setActiveStem: (stemId) => set({ activeStemId: stemId }),
    }),
    {
      name: "waveai-audio-player",
      partialize: (state) => ({ volume: state.volume }),
    },
  ),
);
