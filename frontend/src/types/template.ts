export interface ParamDefinition {
  name: string;
  display_name: string;
  unit?: string;
  param_type: string;
  range_min?: number;
  range_max?: number;
  default?: number | string | boolean;
  depends_on?: string;
}

export interface ParametricTemplate {
  name: string;
  display_name: string;
  part_type: string;
  description: string;
  params: ParamDefinition[];
  constraints: string[];
  code_template: string;
}

export interface ValidateResponse {
  valid: boolean;
  errors: string[];
}
