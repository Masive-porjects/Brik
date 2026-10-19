import {
  getProjectDocument as getProjectDocumentApi,
  putProjectDocument as putProjectDocumentApi,
  deleteProjectDocument as deleteProjectDocumentApi,
  type Group,
  type MasterIntent,
  type MixIntent,
  type Proposal,
  type ProjectDocumentResponse,
  type ProjectDocumentV1,
  type PutDocumentPayload,
  type StemName,
  type StemNode,
} from "@/adapters/api/client";

// The document contract lives in the API adapter (single source of truth,
// mirroring the backend `ProjectDocument`); re-export it so feature consumers
// keep importing it from the store.
export type {
  Group,
  MasterIntent,
  MixIntent,
  Proposal,
  ProjectDocumentResponse,
  ProjectDocumentV1,
  PutDocumentPayload,
  StemName,
  StemNode,
};

/** Default bootstrap document (version 0). Mirrors the backend
 *  `default_document()`: same field names and defaults, so a document built
 *  here validates against `ProjectDocument` unchanged. */
export function defaultDocument(): ProjectDocumentV1 {
  return {
    schema_version: 1,
    structure: {
      stems: {
        drums: {
          display_name: "Drums",
          order: 0,
          group_id: null,
          color_token: null,
          hidden: false,
        },
        bass: {
          display_name: "Bass",
          order: 1,
          group_id: null,
          color_token: null,
          hidden: false,
        },
        other: {
          display_name: "Other",
          order: 2,
          group_id: null,
          color_token: null,
          hidden: false,
        },
        vocals: {
          display_name: "Vocals",
          order: 3,
          group_id: null,
          color_token: null,
          hidden: false,
        },
      },
      groups: [],
    },
    mix_intent: { genre: null, character: null, proposals: [] },
    master_intent: {
      preset_id: null,
      platform_target: null,
      format: "wav",
      output_bit_depth: 24,
      master_name: null,
      parameters: null,
    },
    updated_by: "user",
    updated_at: null,
  };
}

/** Fetches the project document (version 0 if none). */
export async function getProjectDocument(
  projectId: string
): Promise<ProjectDocumentResponse> {
  return getProjectDocumentApi(projectId);
}

/** Writes the project document with optimistic concurrency control. */
export async function putProjectDocument(
  projectId: string,
  payload: PutDocumentPayload
): Promise<ProjectDocumentResponse> {
  return putProjectDocumentApi(projectId, payload);
}

/** Deletes the project document, resetting to bootstrap. */
export async function deleteProjectDocument(projectId: string): Promise<void> {
  await deleteProjectDocumentApi(projectId);
}

/** Approves a pending AI proposal and records the decision in the document.
 *
 *  A `master` proposal carries a partial `MasterIntent`; applying it merges
 *  into `master_intent`. Mix-side proposals (`fader`/`toggle`) are applied to
 *  the live mix state by the autosave path (spec §6.2, invariant I1), so
 *  approving only records the decision here — it is never audible by itself. */
export async function approveProposal(
  projectId: string,
  proposalId: string,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<ProjectDocumentResponse> {
  const proposal = currentDoc.mix_intent.proposals.find(
    (p) => p.id === proposalId
  );
  if (!proposal) throw new Error("Proposal not found");

  const decidedAt = new Date().toISOString();
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    mix_intent: {
      ...currentDoc.mix_intent,
      proposals: currentDoc.mix_intent.proposals.map((p) =>
        p.id === proposalId
          ? { ...p, status: "accepted" as const, decided_at: decidedAt }
          : p
      ),
    },
    master_intent:
      proposal.kind === "master"
        ? {
            ...currentDoc.master_intent,
            ...(proposal.payload as Partial<MasterIntent>),
          }
        : currentDoc.master_intent,
    updated_by: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expected_version: currentVersion,
  });
}

/** Rejects a pending AI proposal. */
export async function rejectProposal(
  projectId: string,
  proposalId: string,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<ProjectDocumentResponse> {
  const decidedAt = new Date().toISOString();
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    mix_intent: {
      ...currentDoc.mix_intent,
      proposals: currentDoc.mix_intent.proposals.map((p) =>
        p.id === proposalId
          ? { ...p, status: "rejected" as const, decided_at: decidedAt }
          : p
      ),
    },
    updated_by: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expected_version: currentVersion,
  });
}

/** Updates the mix character profile (P5). `null` disables the textured render. */
export async function updateMixCharacter(
  projectId: string,
  character: string | null,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<ProjectDocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    mix_intent: { ...currentDoc.mix_intent, character },
    updated_by: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expected_version: currentVersion,
  });
}
/** Updates master intent (preset, platform, format, etc.). */
export async function updateMasterIntent(
  projectId: string,
  intent: Partial<MasterIntent>,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<ProjectDocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    master_intent: { ...currentDoc.master_intent, ...intent },
    updated_by: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expected_version: currentVersion,
  });
}

/** Patches one stem's identity/presentation in `structure.stems`.
 *
 *  The document has no audio path or confirmation flag — those live in
 *  `audio_assets`, not in the document — so this only touches `StemNode`
 *  fields (`display_name`, `order`, `group_id`, `color_token`, `hidden`). */
export async function updateStemNode(
  projectId: string,
  stem: StemName,
  patch: Partial<StemNode>,
  currentDoc: ProjectDocumentV1,
  currentVersion: number
): Promise<ProjectDocumentResponse> {
  const updatedDoc: ProjectDocumentV1 = {
    ...currentDoc,
    structure: {
      ...currentDoc.structure,
      stems: {
        ...currentDoc.structure.stems,
        [stem]: { ...currentDoc.structure.stems[stem], ...patch },
      },
    },
    updated_by: "user",
  };

  return putProjectDocument(projectId, {
    document: updatedDoc,
    expected_version: currentVersion,
  });
}
