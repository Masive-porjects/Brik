"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useMixStateStore } from "@/features/projects/store/mixStateStore";
import {
  getProjectDocument,
  putProjectDocument,
  deleteProjectDocument,
  approveProposal as approveProposalApi,
  rejectProposal as rejectProposalApi,
  updateMasterIntent as updateMasterIntentApi,
  updateStemIdentity as updateStemIdentityApi,
  type ProjectDocumentV1,
  type MasterIntent,
  type StemIdentity,
} from "@/features/projects/store/projectDocumentStore";
import { getProjectMixState } from "@/adapters/api/client";

interface ProjectContextValue {
  projectId: string | null;
  document: ProjectDocumentV1 | null;
  version: number;
  loading: boolean;
  error: string | null;
  loadProject: (projectId: string) => Promise<void>;
  updateMasterIntent: (intent: Partial<MasterIntent>) => Promise<void>;
  approveProposal: (proposalId: string) => Promise<void>;
  rejectProposal: (proposalId: string) => Promise<void>;
  updateStemIdentity: (
    stem: keyof ProjectDocumentV1["stems"],
    identity: StemIdentity
  ) => Promise<void>;
  deleteDocument: () => Promise<void>;
  refreshDocument: () => Promise<void>;
  canSave: boolean;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

interface ProjectProviderProps {
  children: React.ReactNode;
  initialProjectId?: string;
}

export function ProjectProvider({ children, initialProjectId }: ProjectProviderProps) {
  const [projectId, setProjectId] = useState<string | null>(initialProjectId ?? null);
  const [document, setDocument] = useState<ProjectDocumentV1 | null>(null);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProject = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getProjectDocument(id);
      setDocument(res.document);
      setVersion(res.version);
      setProjectId(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load project");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshDocument = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await getProjectDocument(projectId);
      setDocument(res.document);
      setVersion(res.version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh document");
    }
  }, [projectId]);

  const updateDocument = async (payload: {
    document: ProjectDocumentV1;
    expectedVersion: number;
  }) => {
    if (!projectId) throw new Error("No project loaded");
    const res = await putProjectDocument(projectId, {
      document: payload.document,
      expectedVersion: payload.expectedVersion,
    });
    setDocument(res.document);
    setVersion(res.version);
  };

  const updateMasterIntent = useCallback(
    async (intent: Partial<MasterIntent>) => {
      if (!projectId || !document) throw new Error("No project loaded");
      const res = await updateMasterIntentApi(projectId, intent, document, version);
      setDocument(res.document);
      setVersion(res.version);
    },
    [projectId, document, version]
  );

  const approveProposal = useCallback(
    async (proposalId: string) => {
      if (!projectId || !document) throw new Error("No project loaded");
      const res = await approveProposalApi(projectId, proposalId, document, version);
      setDocument(res.document);
      setVersion(res.version);
    },
    [projectId, document, version]
  );

  const rejectProposal = useCallback(
    async (proposalId: string) => {
      if (!projectId || !document) throw new Error("No project loaded");
      const res = await rejectProposalApi(projectId, proposalId, document, version);
      setDocument(res.document);
      setVersion(res.version);
    },
    [projectId, document, version]
  );

  const updateStemIdentity = useCallback(
    async (
      stem: keyof ProjectDocumentV1["stems"],
      identity: StemIdentity
    ) => {
      if (!projectId || !document) throw new Error("No project loaded");
      const res = await updateStemIdentityApi(projectId, stem, identity, document, version);
      setDocument(res.document);
      setVersion(res.version);
    },
    [projectId, document, version]
  );

  const deleteDocument = useCallback(async () => {
    if (!projectId) throw new Error("No project loaded");
    await deleteProjectDocument(projectId);
    setDocument(null);
    setVersion(0);
    setProjectId(null);
  }, [projectId]);

  const canSave = document !== null && !loading;

  return (
    <ProjectContext.Provider
      value={{
        projectId,
        document,
        version,
        loading,
        error,
        loadProject,
        updateMasterIntent,
        approveProposal,
        rejectProposal,
        updateStemIdentity,
        deleteDocument,
        refreshDocument,
        canSave,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const context = useContext(ProjectContext);
  if (!context) {
    throw new Error("useProject must be used within a ProjectProvider");
  }
  return context;
}

// Re-export types
export type { ProjectDocumentV1, MasterIntent, StemIdentity };