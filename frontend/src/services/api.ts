import axios from 'axios';
import type { TooltipSpec, PipelineConfig } from '../types/pipeline.ts';
import type { BenchmarkSummary, BenchmarkReport } from '../types/benchmark.ts';
import type { ParametricTemplate, ValidateResponse } from '../types/template.ts';

const api = axios.create({ baseURL: '/api' });

export async function getTooltips(): Promise<Record<string, TooltipSpec>> {
  const { data } = await api.get<Record<string, TooltipSpec>>('/pipeline/tooltips');
  return data;
}

export async function getPresets(): Promise<Array<{ name: string } & PipelineConfig>> {
  const { data } = await api.get<Array<{ name: string } & PipelineConfig>>('/pipeline/presets');
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

  // Named event listeners (for backend events with `event: xxx` field)
  if (handlers.onProgress) {
    source.addEventListener('progress', (e: MessageEvent) => {
      handlers.onProgress!(JSON.parse(e.data));
    });
  }
  if (handlers.onComplete) {
    source.addEventListener('complete', (e: MessageEvent) => {
      handlers.onComplete!(JSON.parse(e.data));
    });
  }
  if (handlers.onError) {
    source.addEventListener('error', (e: MessageEvent) => {
      handlers.onError!(JSON.parse(e.data));
    });
  }

  // Fallback: generic messages without event type
  source.onmessage = (e: MessageEvent) => {
    const data = JSON.parse(e.data);
    if (data.event === 'progress' && handlers.onProgress) {
      handlers.onProgress(data);
    } else if (data.event === 'complete' && handlers.onComplete) {
      handlers.onComplete(data);
    } else if (data.event === 'error' && handlers.onError) {
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

export default api;
