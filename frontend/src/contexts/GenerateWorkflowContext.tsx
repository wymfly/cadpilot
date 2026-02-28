import { createContext, useContext, useState, type ReactNode } from 'react';
import { useGenerateWorkflow, type WorkflowState } from '../pages/Generate/GenerateWorkflow.tsx';
import { DEFAULT_CONFIG } from '../components/PipelineConfigBar/index.tsx';
import type { PipelineConfig } from '../types/pipeline.ts';
import type { DrawingSpec } from '../types/generate.ts';

interface GenerateWorkflowContextValue {
  workflow: WorkflowState;
  startTextGenerate: (text: string, config?: PipelineConfig) => Promise<void>;
  startDrawingGenerate: (file: File, config?: PipelineConfig) => Promise<void>;
  confirmParams: (params: Record<string, number>) => Promise<void>;
  confirmDrawingSpec: (spec: DrawingSpec, disclaimerAccepted: boolean) => Promise<void>;
  reset: () => void;
  pipelineConfig: PipelineConfig;
  setPipelineConfig: (config: PipelineConfig) => void;
}

const GenerateWorkflowContext = createContext<GenerateWorkflowContextValue | null>(null);

export function GenerateWorkflowProvider({ children }: { children: ReactNode }) {
  const { state, startTextGenerate, startDrawingGenerate, confirmParams, confirmDrawingSpec, reset } =
    useGenerateWorkflow();
  const [pipelineConfig, setPipelineConfig] = useState<PipelineConfig>(DEFAULT_CONFIG);

  return (
    <GenerateWorkflowContext.Provider
      value={{
        workflow: state,
        startTextGenerate,
        startDrawingGenerate,
        confirmParams,
        confirmDrawingSpec,
        reset,
        pipelineConfig,
        setPipelineConfig,
      }}
    >
      {children}
    </GenerateWorkflowContext.Provider>
  );
}

export function useGenerateWorkflowContext(): GenerateWorkflowContextValue {
  const ctx = useContext(GenerateWorkflowContext);
  if (!ctx) {
    throw new Error('useGenerateWorkflowContext must be used within GenerateWorkflowProvider');
  }
  return ctx;
}
