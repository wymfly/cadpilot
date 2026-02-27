export type OrganicJobStatus =
  | 'created'
  | 'analyzing'
  | 'generating'
  | 'post_processing'
  | 'completed'
  | 'failed';

export type OrganicPhase = 'idle' | OrganicJobStatus;

export type QualityMode = 'draft' | 'standard' | 'high';
export type ProviderPreference = 'auto' | 'tripo3d' | 'hunyuan3d';
export type CutType = 'flat_bottom' | 'hole' | 'slot';
export type CutDirection = 'top' | 'bottom' | 'front' | 'back' | 'left' | 'right';

export interface EngineeringCut {
  type: CutType;
  diameter?: number;
  depth?: number;
  width?: number;
  length?: number;
  position?: [number, number, number];
  direction?: CutDirection;
  offset?: number;
}

export interface OrganicConstraints {
  bounding_box: [number, number, number] | null;
  engineering_cuts: EngineeringCut[];
}

export interface MeshStats {
  vertex_count: number;
  face_count: number;
  is_watertight: boolean;
  volume_cm3: number | null;
  bounding_box: Record<string, number>;
  has_non_manifold: boolean;
  repairs_applied: string[];
  boolean_cuts_applied: number;
}

export interface OrganicWorkflowState {
  phase: OrganicPhase;
  jobId: string | null;
  message: string;
  progress: number;
  error: string | null;
  modelUrl: string | null;
  stlUrl: string | null;
  threemfUrl: string | null;
  meshStats: MeshStats | null;
  postProcessStep: string | null;
}

export interface OrganicGenerateRequest {
  prompt: string;
  constraints: OrganicConstraints;
  quality_mode: QualityMode;
  provider: ProviderPreference;
}
