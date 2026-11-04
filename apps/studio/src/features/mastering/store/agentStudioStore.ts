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
  hydrated: boolean;
  appendMessage: (sessionId: string, message: AgentChatMessage) => void;
  clearStems: () => void;
  beginStemJob: (sessionId: string, jobId: string) => void;
  setCompletedStems: (
    jobId: string,
    sessionId: string,
    stemNames: readonly string[],
  ) => void;
}

type PersistedAgentStudioState = Pick<AgentStudioState, "messagesBySession">;

const STEM_ORDER: readonly AgentStemName[] = ["drums", "bass", "other", "vocals"];
const MAX_MESSAGES_PER_SESSION = 100;

export const useAgentStudioStore = create<AgentStudioState>()(
  persist<AgentStudioState, [], [], PersistedAgentStudioState>(
    (set) => ({
      messagesBySession: {},
      activeStemJobId: null,
      activeStemSessionId: null,
      completedStems: [],
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
        }),
      beginStemJob: (sessionId, jobId) =>
        set({
          activeStemJobId: jobId,
          activeStemSessionId: sessionId,
          completedStems: [],
        }),
      setCompletedStems: (jobId, sessionId, stemNames) =>
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
          return { completedStems: STEM_ORDER.filter((name) => complete.has(name)) };
        }),
    }),
    {
      name: "waveai-agent-studio",
      storage: createJSONStorage(() => localStorage),
      skipHydration: true,
      partialize: (state) => ({ messagesBySession: state.messagesBySession }),
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as PersistedAgentStudioState),
        hydrated: current.hydrated,
      }),
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
