import {
  getProjectDocument as getProjectDocumentApi,
  putProjectDocument as putProjectDocumentApi,
  deleteProjectDocument as deleteProjectDocumentApi,
} from "@/adapters/api/client";

/** Project Document V1 types matching backend schema. */
export interface StemIdentity {
  name: string;
  storagePath: string;
  confirmed: boolean;
}

export interface PendingProposal {
  id: string;
  type: "fader" | "trim" | "balance" | "dimension" | "master_intent";
  payload: unknown;
  createdAt: string;
  status: "pending" | "accepted" | "rejected";
}

export interface MasterIntent {
  presetId: "universal" | "streaming" | "club" | "cd" | "custom";
  platformTarget: "spotify" | "apple_music" | "youtube" | "tidal" | "club" | "cd" | "custom";
  format: "wav" | "mp3";
  outputBitDepth: 16 | 24 | 32;
  masterName?: string;
  parameters?: Record<string, number | boolean>;
}

export interface ProjectDocumentV1 {
  schemaVersion: 1;
  stems: Record<string, StemIdentity>;
  pendingProposals: PendingProposal[];
  masterIntent: MasterIntent;
  updatedAt: string;
  updatedBy: "user" | "ai";
}

/** Payload for PUT /projects/{id}/document with OCC. */
export interface PutDocumentPayload {
  document: ProjectDocumentV1;
  expectedVersion: number;
}

/** Response from GET/PUT /projects/{id}/document. */
export interface DocumentResponse {
  projectId: string;
  version: number;
  document: ProjectDocumentV1;
  updatedAt: string | null;
}

/** Default bootstrap document (version 0). */
export function defaultDocument(): ProjectDocumentV1 {
  return {
    schemaVersion: 1,
    stems: {
      drums: { name: "drums", storagePath: "", confirmed: false },
      bass: { name: "bass", storagePath: "", confirmed: false },
      other: { name: "other", storagePath: "", confirmed: false },
      vocals: { name: "vocals", storagePath: "", confirmed: false },
    },
    pendingProposals: [],
    masterIntent: {
      presetId: "universal",
      platformTarget: "spotify",
      format: "wav",
      outputBitDepth: 24,
      masterName: "",
      parameters: {},
    },
    updatedAt: new Date().toISOString(),
    updatedBy: "user",
  };
}

/** Fetches the project document (version 0 if none). */
export async function getProjectDocument(
  projectId: string
): Promise<DocumentResponse> {
  return getProjectDocumentApi(projectId);
}

/** Writes the project document with optimistic concurrency control. */
export async function putProjectDocument(
  projectId: string,
  payload: PutDocumentPayload
): Promise<DocumentResponse> {
  return putProjectDocumentApi(projectId, payload);
}

/** Deletes the project document, resetting to bootstrap. */
export async function deleteProjectDocument(projectId: string): Promise<void> {
  await deleteProjectDocumentApi(projectId);
}

/** Approves a pending AI proposal and applies it to the document. */
export async function approveProposal(
  projectId: string,
  proposalId: string,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<DocumentResponse> {
  const proposal = currentDoc.pendingProposals.find((p) => p.id === proposalId);
  if (!proposal) throw new Error("Proposal not found");

  // Apply the proposal based on type
  const updatedDoc: ProjectDocumentV1 = { ...currentDoc };
  updatedDoc.pendingProposals = updatedDoc.pendingProposals.map((p) =>
    p.id === proposalId ? { ...p, status: "accepted" as const } : p
  );

  switch (proposal.type) {
    case "fader":
    case "trim":
    case "balance":
    case "dimension":
      // Mix-side proposals (faders/toggles) are applied to the live mix
      // state by the store's autosave path (spec §6.2, invariant I1).
      // Approving only records the decision in the document.
      break;
    case "master_intent": {
      const payload = proposal.payload as Partial<MasterIntent>;
      updatedDoc.masterIntent = { ...updatedDoc.masterIntent, ...payload };
      break;
    }
  }

  updatedDoc.updatedAt = new Date().toISOString();
  updatedDoc.updatedBy = "user";

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expectedVersion: currentVersion,
  });
}

/** Rejects a pending AI proposal. */
export async function rejectProposal(
  projectId: string,
  proposalId: string,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<DocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    pendingProposals: currentDoc.pendingProposals.map((p) =>
      p.id === proposalId ? { ...p, status: "rejected" as const } : p
    ),
    updatedAt: new Date().toISOString(),
    updatedBy: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expectedVersion: currentVersion,
  });
}

/** Updates master intent (preset, platform, format, etc.). */
export async function updateMasterIntent(
  projectId: string,
  intent: Partial<MasterIntent>,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<DocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    masterIntent: { ...currentDoc.masterIntent, ...intent },
    updatedAt: new Date().toISOString(),
    updatedBy: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expectedVersion: currentVersion,
  });
}

/** Updates stem identity (e.g., after separation confirmation). */
export async function updateStemIdentity(
  projectId: string,
  stem: keyof ProjectDocumentV1["stems"],
  identity: { name: string; storagePath: string; confirmed: boolean },
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<DocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    stems: { ...currentDoc.stems, [stem]: identity },
    updatedAt: new Date().toISOString(),
    updatedBy: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expectedVersion: currentVersion,
  });
}