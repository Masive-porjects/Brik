"use client";

import React, { createContext, useContext } from "react";
import { useMasteringWorkflow } from "../hooks/useMasteringWorkflow";

type MasteringWorkflowReturn = ReturnType<typeof useMasteringWorkflow>;

const MasteringContext = createContext<MasteringWorkflowReturn | null>(null);

export function MasteringProvider({ children }: { children: React.ReactNode }) {
  const workflow = useMasteringWorkflow();
  return (
    <MasteringContext.Provider value={workflow}>
      {children}
    </MasteringContext.Provider>
  );
}

export function useMastering(): MasteringWorkflowReturn {
  const ctx = useContext(MasteringContext);
  if (!ctx) {
    throw new Error("useMastering must be used within a MasteringProvider");
  }
  return ctx;
}
