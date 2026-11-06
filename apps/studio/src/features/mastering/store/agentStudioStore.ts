"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type AgentStemName = "drums" | "bass" | "other" | "vocals";

export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
  escalated?: boolean;
  intentPill?: boolean;
}

interface AgentStudioState {
  messagesBySession: Record<string, AgentChatMessage[]>;
  activeStemJobId: string | null;
  activeStemSessionId: string | null;
  completedStems: AgentStemName[];
  /** Presencia real por stem medida por el backend (RMS ≥ −50 dBFS).
   *  `true` = tiene audio, `false` = silencio/vacío, `undefined` = no medido aún. */
  stemPresence: Record<string, boolean>;
  hydrated: boolean;
  appendMessage: (sessionId: string, message: AgentChatMessage) => void;
  clearStems: () => void;
  beginStemJob: (sessionId: string, jobId: string) => void;
  setCompletedStems: (
    jobId: string,
    sessionId: string,
    stemNames: readonly string[],
    stemPresence?: Record<string, boolean>,
  ) => void;
}

/**
 * Lo que sobrevive a un refresh: chat + metadatos livianos de los stems.
 *
 * Los stems NO guardan blobs ni URLs firmadas (caducan); sólo el id del job y
 * la sesión que los produjo. Al recargar, `AgentStemStack` reconstruye las
 * URLs con `getStemUrl(sessionId, name)` y las ondas se vuelven a pedir al
 * backend. Sin esto, refrescar borraba el panel aunque el job ya hubiera
 * terminado.
 */
type PersistedAgentStudioState = Pick<
  AgentStudioState,
  | "messagesBySession"
  | "activeStemJobId"
  | "activeStemSessionId"
  | "completedStems"
  | "stemPresence"
>;

const STEM_ORDER: readonly AgentStemName[] = ["drums", "bass", "other", "vocals"];
const MAX_MESSAGES_PER_SESSION = 100;

export const useAgentStudioStore = create<AgentStudioState>()(
  persist<AgentStudioState, [], [], PersistedAgentStudioState>(
    (set) => ({
      messagesBySession: {},
      activeStemJobId: null,
      activeStemSessionId: null,
      completedStems: [],
      stemPresence: {},
      hydrated: false,
      appendMessage: (sessionId, message) =>
        set((state) => {
          const previous = state.messagesBySession[sessionId] ?? [];
          return {
            messagesBySession: {
              ...state.messagesBySession,
              [sessionId]: [...previous, message].slice(-MAX_MESSAGES_PER_SESSION),
            },
          };
        }),
      clearStems: () =>
        set({
          activeStemJobId: null,
          activeStemSessionId: null,
          completedStems: [],
          stemPresence: {},
        }),
      beginStemJob: (sessionId, jobId) =>
        set({
          activeStemJobId: jobId,
          activeStemSessionId: sessionId,
          completedStems: [],
          stemPresence: {},
        }),
      setCompletedStems: (
        jobId: string,
        sessionId: string,
        stemNames: readonly string[],
        stemPresence?: Record<string, boolean>,
      ) =>
        set((state) => {
          if (
            state.activeStemJobId !== jobId ||
            state.activeStemSessionId !== sessionId
          ) {
            return state;
          }
          const complete = new Set([
            ...state.completedStems,
            ...stemNames.filter((name): name is AgentStemName =>
              STEM_ORDER.includes(name as AgentStemName),
            ),
          ]);
          return {
            completedStems: STEM_ORDER.filter((name) => complete.has(name)),
            stemPresence: stemPresence
              ? { ...state.stemPresence, ...stemPresence }
              : state.stemPresence,
          };
        }),
    }),
    {
      name: "waveai-agent-studio",
      storage: createJSONStorage(() => localStorage),
      skipHydration: true,
      partialize: (state) => ({
        messagesBySession: state.messagesBySession,
        activeStemJobId: state.activeStemJobId,
        activeStemSessionId: state.activeStemSessionId,
        completedStems: state.completedStems,
        stemPresence: state.stemPresence,
      }),
      merge: (persisted, current) => {
        // Tolerate an older persisted shape (only `messagesBySession`): a
        // missing field falls back to the live default instead of `undefined`.
        const saved = (persisted ?? {}) as Partial<PersistedAgentStudioState>;
        return {
          ...current,
          messagesBySession: saved.messagesBySession ?? current.messagesBySession,
          activeStemJobId: saved.activeStemJobId ?? null,
          activeStemSessionId: saved.activeStemSessionId ?? null,
          completedStems: Array.isArray(saved.completedStems)
            ? saved.completedStems
            : current.completedStems,
          stemPresence: saved.stemPresence ?? current.stemPresence,
          hydrated: current.hydrated,
        };
      },
    },
  ),
);

let hydrationPromise: Promise<void> | null = null;

/** Hydrate persisted chat after mount so server and first client render match. */
export function hydrateAgentStudioStore(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (!hydrationPromise) {
    hydrationPromise = Promise.resolve(useAgentStudioStore.persist.rehydrate())
      .catch(() => undefined)
      .then(() => {
        useAgentStudioStore.setState({ hydrated: true });
      });
  }
  return hydrationPromise;
}
