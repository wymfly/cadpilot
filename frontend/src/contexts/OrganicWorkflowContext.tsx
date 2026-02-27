import { createContext, useContext, useState, type ReactNode } from 'react';
import {
  useOrganicWorkflow,
  type StartGenerateOptions,
} from '../pages/OrganicGenerate/OrganicWorkflow.tsx';
import type {
  OrganicWorkflowState,
  OrganicConstraints,
  QualityMode,
  ProviderPreference,
} from '../types/organic.ts';

interface OrganicWorkflowContextValue {
  workflow: OrganicWorkflowState;
  startGenerate: (opts: StartGenerateOptions) => Promise<void>;
  reset: () => void;
  constraints: OrganicConstraints;
  setConstraints: (c: OrganicConstraints) => void;
  qualityMode: QualityMode;
  setQualityMode: (m: QualityMode) => void;
  provider: ProviderPreference;
  setProvider: (p: ProviderPreference) => void;
}

const OrganicWorkflowContext = createContext<OrganicWorkflowContextValue | null>(null);

const DEFAULT_CONSTRAINTS: OrganicConstraints = {
  bounding_box: null,
  engineering_cuts: [],
};

export function OrganicWorkflowProvider({ children }: { children: ReactNode }) {
  const { state, startGenerate, reset } = useOrganicWorkflow();
  const [constraints, setConstraints] = useState<OrganicConstraints>(DEFAULT_CONSTRAINTS);
  const [qualityMode, setQualityMode] = useState<QualityMode>('standard');
  const [provider, setProvider] = useState<ProviderPreference>('auto');

  return (
    <OrganicWorkflowContext.Provider
      value={{
        workflow: state,
        startGenerate,
        reset,
        constraints,
        setConstraints,
        qualityMode,
        setQualityMode,
        provider,
        setProvider,
      }}
    >
      {children}
    </OrganicWorkflowContext.Provider>
  );
}

export function useOrganicWorkflowContext(): OrganicWorkflowContextValue {
  const ctx = useContext(OrganicWorkflowContext);
  if (!ctx) {
    throw new Error('useOrganicWorkflowContext must be used within OrganicWorkflowProvider');
  }
  return ctx;
}
