import { beforeEach, describe, expect, it } from "vitest";

import {
  hydrateAgentStudioStore,
  useAgentStudioStore,
  type AgentChatMessage,
} from "./agentStudioStore";

const firstMessage: AgentChatMessage = {
  role: "user",
  content: "Dale más presencia a la voz",
  ts: 100,
};

describe("agent studio store", () => {
  beforeEach(async () => {
    localStorage.clear();
    useAgentStudioStore.setState({
      messagesBySession: {},
      activeStemJobId: null,
      activeStemSessionId: null,
      completedStems: [],
      stemPresence: {},
      hydrated: false,
    });
    await useAgentStudioStore.persist.clearStorage();
  });

  it("persists chat messages by session and restores them after rehydration", async () => {
    useAgentStudioStore.getState().appendMessage("session-a", firstMessage);

    const saved = JSON.parse(localStorage.getItem("waveai-agent-studio") ?? "null");
    expect(saved.state.messagesBySession["session-a"]).toEqual([firstMessage]);
    // El chat y los metadatos livianos de stems sobreviven al refresh; las
    // URLs de audio no se guardan (se reconstruyen desde el backend).
    expect(Object.keys(saved.state).sort()).toEqual(
      [
        "activeStemJobId",
        "activeStemSessionId",
        "completedStems",
        "messagesBySession",
        "stemPresence",
      ].sort(),
    );

    const persisted = localStorage.getItem("waveai-agent-studio");
    useAgentStudioStore.setState({ messagesBySession: {} });
    if (persisted) localStorage.setItem("waveai-agent-studio", persisted);
    await useAgentStudioStore.persist.rehydrate();

    expect(useAgentStudioStore.getState().messagesBySession["session-a"]).toEqual([
      firstMessage,
    ]);
  });

  it("restores completed stem metadata after rehydration", async () => {
    const store = useAgentStudioStore.getState();
    store.beginStemJob("session-a", "job-1");
    store.setCompletedStems("job-1", "session-a", ["drums", "vocals"], {
      drums: true,
      vocals: false,
    });

    const persisted = localStorage.getItem("waveai-agent-studio");
    useAgentStudioStore.setState({
      activeStemJobId: null,
      activeStemSessionId: null,
      completedStems: [],
      stemPresence: {},
    });
    if (persisted) localStorage.setItem("waveai-agent-studio", persisted);
    await useAgentStudioStore.persist.rehydrate();

    const restored = useAgentStudioStore.getState();
    expect(restored.activeStemJobId).toBe("job-1");
    expect(restored.activeStemSessionId).toBe("session-a");
    expect(restored.completedStems).toEqual(["drums", "vocals"]);
    expect(restored.stemPresence).toEqual({ drums: true, vocals: false });
  });

  it("clears prior stems immediately and rejects stale updates from older jobs", () => {
    const store = useAgentStudioStore.getState();
    store.beginStemJob("session-a", "job-new");
    store.setCompletedStems("job-new", "session-a", ["drums", "bass"]);
    expect(useAgentStudioStore.getState().completedStems).toEqual(["drums", "bass"]);

    store.clearStems();
    expect(useAgentStudioStore.getState().completedStems).toEqual([]);
    expect(useAgentStudioStore.getState().activeStemJobId).toBeNull();

    store.beginStemJob("session-a", "job-latest");
    store.setCompletedStems("job-new", "session-a", ["vocals"]);
    expect(useAgentStudioStore.getState().completedStems).toEqual([]);
    store.setCompletedStems("job-latest", "session-a", ["vocals"]);
    expect(useAgentStudioStore.getState().completedStems).toEqual(["vocals"]);
  });
});
