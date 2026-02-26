export interface StandardEntry {
  category: string;
  name: string;
  params: Record<string, number | string>;
}

export interface ParamRecommendation {
  param_name: string;
  value: number;
  unit: string;
  reason: string;
  source: string;
}

export interface ConstraintViolation {
  constraint: string;
  message: string;
  severity: 'error' | 'warning';
}

export interface RecommendRequest {
  part_type: string;
  known_params: Record<string, number>;
}

export interface RecommendResponse {
  recommendations: ParamRecommendation[];
}

export interface CheckRequest {
  part_type: string;
  params: Record<string, number>;
}

export interface CheckResponse {
  valid: boolean;
  violations: ConstraintViolation[];
}
