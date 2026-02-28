export interface PrintProfile {
  name: string;
  technology: string;
  min_wall_thickness: number;
  max_overhang_angle: number;
  min_hole_diameter: number;
  min_rib_thickness: number;
  build_volume: [number, number, number];
}

export interface PrintIssue {
  check: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  value?: number;
  threshold?: number;
  suggestion: string;
}

export interface MaterialEstimate {
  filament_weight_g: number;
  filament_length_m: number;
  cost_estimate_cny: number;
}

export interface TimeEstimate {
  total_minutes: number;
  layer_count: number;
}

export interface PrintabilityResult {
  printable: boolean;
  profile: string;
  issues: PrintIssue[];
  material_volume_cm3?: number;
  bounding_box?: { x: number; y: number; z: number };
  material_estimate?: MaterialEstimate | null;
  time_estimate?: TimeEstimate | null;
}

export type ProfileKey = 'fdm_standard' | 'sla_standard' | 'sls_standard';

export const PROFILE_LABELS: Record<ProfileKey, { label: string; tech: string }> = {
  fdm_standard: { label: 'FDM 标准', tech: 'FDM' },
  sla_standard: { label: 'SLA 标准', tech: 'SLA' },
  sls_standard: { label: 'SLS 标准', tech: 'SLS' },
};
