// --- Legacy config types (backward compat with old PipelineConfigBar) ---

export interface PipelineConfig {
  preset: 'fast' | 'balanced' | 'precise' | 'custom';

  // Stage 1: Drawing analysis enhancements
  ocr_assist: boolean;
  two_pass_analysis: boolean;
  multi_model_voting: boolean;
  self_consistency_runs: number;

  // Stage 2: Code generation
  best_of_n: number;
  rag_enabled: boolean;
  api_whitelist: boolean;
  ast_pre_check: boolean;

  // Stage 3: Validation
  volume_check: boolean;
  topology_check: boolean;
  cross_section_check: boolean;

  // Stage 4: Refinement loop
  max_refinements: number;
  multi_view_render: boolean;
  structured_feedback: boolean;
  rollback_on_degrade: boolean;
  contour_overlay: boolean;

  // Stage 5: Output
  printability_check: boolean;
  output_formats: string[];
}

export interface TooltipSpec {
  title: string;
  description: string;
  when_to_use: string;
  cost: string;
  default: string;
}

export interface PresetInfo {
  name: string;
  config: PipelineConfig;
}

// --- Node-level config types (new plugin pipeline architecture) ---

/** Backend GET /pipeline/nodes response item */
export interface PipelineNodeDescriptor {
  name: string;
  display_name: string;
  requires: (string | string[])[];
  produces: string[];
  input_types: string[];
  strategies: string[];
  default_strategy: string | null;
  is_entry: boolean;
  is_terminal: boolean;
  supports_hitl: boolean;
  non_fatal: boolean;
  description: string | null;
  config_schema?: Record<string, unknown>;
  fallback_chain?: string[];
}

/** Per-node config (enabled + strategy + custom params) */
export interface NodeLevelConfig {
  enabled?: boolean;
  strategy?: string;
  [key: string]: unknown;
}

/** Node-level preset from GET /pipeline/node-presets */
export interface NodeLevelPreset {
  name: string;
  display_name: string;
  description: string;
  config: Record<string, NodeLevelConfig>;
}

/** Validate response from POST /pipeline/validate */
export interface PipelineValidateResponse {
  valid: boolean;
  error?: string;
  node_count?: number;
  topology?: string[];
  interrupt_before?: string[];
}

/** Strategy availability per node — GET /pipeline/strategy-availability */
export interface StrategyAvailabilityMap {
  [nodeName: string]: {
    [strategyName: string]: {
      available: boolean;
      reason?: string;
    };
  };
}
