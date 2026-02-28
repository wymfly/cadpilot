/** Types for the generate workflow (Phase 4 Task 4.6). */

export type JobStatus =
  | 'created'
  | 'intent_parsed'
  | 'awaiting_confirmation'
  | 'awaiting_drawing_confirmation'
  | 'generating'
  | 'refining'
  | 'completed'
  | 'failed'
  | 'validation_failed';

/**
 * Job model for generate workflow SSE events.
 * See also: api.ts JobDetail for the history API variant.
 */
export interface Job {
  job_id: string;
  status: JobStatus;
  input_type: 'text' | 'drawing';
  input_text: string;
  intent: IntentSpec | null;
  precise_spec: PreciseSpec | null;
  recommendations: ParamRecommendationItem[];
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}

export interface IntentSpec {
  part_category: string;
  part_type: string | null;
  known_params: Record<string, number>;
  missing_params: string[];
  constraints: string[];
  reference_image: string | null;
  confidence: number;
  raw_text: string;
}

export interface PreciseSpec {
  part_type: string;
  description: string;
  overall_dimensions: Record<string, number>;
  source: 'text_input' | 'drawing_input' | 'image_input';
  confirmed_by_user: boolean;
}

export interface ParamRecommendationItem {
  param_name: string;
  value: number;
  unit: string;
  reason: string;
  source: string;
}

/** SSE event payload shapes. */
export interface SSEEvent {
  event: string;
  data: {
    job_id: string;
    status: JobStatus;
    message?: string;
    confirmed_params?: Record<string, number>;
    [key: string]: unknown;
  };
}

/** DrawingSpec extracted by AI from engineering drawings. */
export interface DrawingSpecBaseBody {
  method: 'revolve' | 'extrude' | 'loft' | 'sweep' | 'shell';
  [key: string]: unknown;
}

export interface DrawingSpecFeature {
  type: string;
  [key: string]: unknown;
}

export interface DrawingSpec {
  part_type: string;
  overall_dimensions: Record<string, number>;
  base_body: DrawingSpecBaseBody;
  features: DrawingSpecFeature[];
  notes: string[];
  confidence?: number;
}

/** Workflow UI state (superset of JobStatus for frontend-specific states). */
export type WorkflowPhase =
  | 'idle'
  | 'parsing'
  | 'confirming'
  | 'drawing_review'
  | 'generating'
  | 'refining'
  | 'completed'
  | 'failed';
