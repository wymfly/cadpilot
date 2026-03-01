import axios from 'axios';
import type { TooltipSpec, PipelineConfig } from '../types/pipeline.ts';
import type { BenchmarkSummary, BenchmarkReport } from '../types/benchmark.ts';
import type { ParametricTemplate, ValidateResponse } from '../types/template.ts';
import type {
  StandardEntry,
  RecommendRequest,
  RecommendResponse,
  CheckRequest,
  CheckResponse,
} from '../types/standard.ts';
import type { PrintProfile, PrintabilityResult } from '../types/printability.ts';

const api = axios.create({ baseURL: '/api' });

/** 统一 API 错误结构 */
export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

/** 从 axios 错误中提取统一错误信息 */
export function extractApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err) && err.response?.data?.error) {
    const e = err.response.data.error as ApiError;
    return { code: e.code ?? 'UNKNOWN', message: e.message ?? '未知错误', details: e.details };
  }
  if (err instanceof Error) {
    return { code: 'NETWORK_ERROR', message: err.message };
  }
  return { code: 'UNKNOWN', message: '未知错误' };
}


export async function getTooltips(): Promise<Record<string, TooltipSpec>> {
  const { data } = await api.get<Record<string, TooltipSpec>>('/v1/pipeline/tooltips');
  return data;
}

export async function getPresets(): Promise<Array<{ name: string } & PipelineConfig>> {
  const { data } = await api.get<Array<{ name: string } & PipelineConfig>>('/v1/pipeline/presets');
  return data;
}

/**
 * Create an SSE connection that handles both named events and generic messages.
 */
export function createSSEConnection(
  url: string,
  handlers: {
    onProgress?: (data: unknown) => void;
    onComplete?: (data: unknown) => void;
    onError?: (data: unknown) => void;
  },
  onConnectionError?: (error: Event) => void,
): EventSource {
  const source = new EventSource(url);

  const safeParse = (raw: string): unknown => {
    try { return JSON.parse(raw); }
    catch (err) { console.warn('Failed to parse SSE data:', raw, err); return null; }
  };

  // Named event listeners (for backend events with `event: xxx` field)
  if (handlers.onProgress) {
    source.addEventListener('progress', (e: MessageEvent) => {
      const data = safeParse(e.data);
      if (data) handlers.onProgress!(data);
    });
  }
  if (handlers.onComplete) {
    source.addEventListener('completed', (e: MessageEvent) => {
      const data = safeParse(e.data);
      if (data) handlers.onComplete!(data);
    });
  }
  if (handlers.onError) {
    source.addEventListener('failed', (e: MessageEvent) => {
      const data = safeParse(e.data);
      if (data) handlers.onError!(data);
    });
  }

  // Fallback: generic messages without event type
  source.onmessage = (e: MessageEvent) => {
    const data = safeParse(e.data) as Record<string, unknown> | null;
    if (!data) return;
    if (data.event === 'progress' && handlers.onProgress) {
      handlers.onProgress(data);
    } else if (data.event === 'completed' && handlers.onComplete) {
      handlers.onComplete(data);
    } else if (data.event === 'failed' && handlers.onError) {
      handlers.onError(data);
    }
  };

  if (onConnectionError) {
    source.onerror = onConnectionError;
  }
  return source;
}

// Benchmark API
export async function getBenchmarkHistory(): Promise<BenchmarkSummary[]> {
  const { data } = await api.get<BenchmarkSummary[]>('/benchmark/history');
  return data;
}

export async function getBenchmarkReport(runId: string): Promise<BenchmarkReport> {
  const { data } = await api.get<BenchmarkReport>(`/benchmark/history/${runId}`);
  return data;
}

export async function getBenchmarkDatasets(): Promise<string[]> {
  const { data } = await api.get<string[]>('/benchmark/datasets');
  return data;
}

// Template API
export async function getTemplates(partType?: string): Promise<ParametricTemplate[]> {
  const params = partType ? { part_type: partType } : {};
  const { data } = await api.get<ParametricTemplate[]>('/templates', { params });
  return data;
}

export async function getTemplate(name: string): Promise<ParametricTemplate> {
  const { data } = await api.get<ParametricTemplate>(`/templates/${name}`);
  return data;
}

export async function createTemplate(
  template: Partial<ParametricTemplate>,
): Promise<ParametricTemplate> {
  const { data } = await api.post<ParametricTemplate>('/templates', template);
  return data;
}

export async function updateTemplate(
  name: string,
  template: Partial<ParametricTemplate>,
): Promise<ParametricTemplate> {
  const { data } = await api.put<ParametricTemplate>(
    `/templates/${name}`,
    template,
  );
  return data;
}

export async function deleteTemplate(name: string): Promise<void> {
  await api.delete(`/templates/${name}`);
}

export async function validateTemplateParams(
  name: string,
  params: Record<string, unknown>,
): Promise<ValidateResponse> {
  const { data } = await api.post<ValidateResponse>(
    `/templates/${name}/validate`,
    params,
  );
  return data;
}

// Standards API
export async function getStandardCategories(): Promise<string[]> {
  const { data } = await api.get<string[]>('/standards');
  return data;
}

export async function getStandardEntries(category: string): Promise<StandardEntry[]> {
  const { data } = await api.get<StandardEntry[]>(`/standards/${category}`);
  return data;
}

export async function recommendParams(
  request: RecommendRequest,
): Promise<RecommendResponse> {
  const { data } = await api.post<RecommendResponse>('/standards/recommend', request);
  return data;
}

export async function checkConstraints(
  request: CheckRequest,
): Promise<CheckResponse> {
  const { data } = await api.post<CheckResponse>('/standards/check', request);
  return data;
}

// Print Profile API
export async function listPrintProfiles(): Promise<
  Array<PrintProfile & { is_preset: boolean }>
> {
  const { data } = await api.get<Array<PrintProfile & { is_preset: boolean }>>(
    '/print-profiles',
  );
  return data;
}

export async function createPrintProfile(
  body: Record<string, unknown>,
): Promise<PrintProfile & { is_preset: boolean }> {
  const { data } = await api.post<PrintProfile & { is_preset: boolean }>(
    '/print-profiles',
    body,
  );
  return data;
}

export async function updatePrintProfile(
  name: string,
  body: Record<string, unknown>,
): Promise<PrintProfile & { is_preset: boolean }> {
  const { data } = await api.put<PrintProfile & { is_preset: boolean }>(
    `/print-profiles/${name}`,
    body,
  );
  return data;
}

export async function deletePrintProfile(name: string): Promise<void> {
  await api.delete(`/print-profiles/${name}`);
}

// History API
export interface JobSummary {
  job_id: string;
  status: string;
  input_type: 'text' | 'drawing';
  input_text: string;
  created_at: string;
  result?: Record<string, unknown> | null;
}

export interface PaginatedJobsResponse {
  items: JobSummary[];
  total: number;
  page: number;
  page_size: number;
}

export async function listJobs(params?: {
  page?: number;
  page_size?: number;
  status?: string;
  input_type?: string;
}): Promise<PaginatedJobsResponse> {
  const { data } = await api.get<PaginatedJobsResponse>('/v1/jobs', { params });
  return data;
}

export interface JobDetail {
  job_id: string;
  status: string;
  input_type: 'text' | 'drawing';
  input_text: string;
  intent: Record<string, unknown> | null;
  precise_spec: Record<string, unknown> | null;
  drawing_spec: Record<string, unknown> | null;
  result: {
    model_url?: string;
    step_path?: string;
  } | null;
  printability: PrintabilityResult | null;
  error: string | null;
  created_at: string;
}

export async function getJobDetail(jobId: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(`/v1/jobs/${jobId}`);
  return data;
}

export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/v1/jobs/${jobId}`);
}

export async function regenerateJob(jobId: string): Promise<{ job_id: string; cloned_from: string; status: string }> {
  const { data } = await api.post<{ job_id: string; cloned_from: string; status: string }>(`/v1/jobs/${jobId}/regenerate`);
  return data;
}

// Preview API
export async function previewParametric(
  templateName: string,
  params: Record<string, number>,
  signal?: AbortSignal,
): Promise<{ glb_url: string }> {
  const { data } = await api.post<{ glb_url: string }>('/v1/preview/parametric', {
    template_name: templateName,
    params,
  }, { signal });
  return data;
}

export default api;
