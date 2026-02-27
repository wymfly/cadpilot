import { useState, useCallback, useRef } from 'react';
import { Steps, Alert, Spin, Result, Card, Typography } from 'antd';
import {
  LoadingOutlined,
  CheckCircleOutlined,
  EditOutlined,
  RocketOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import type { WorkflowPhase } from '../../types/generate.ts';
import type { ParamDefinition } from '../../types/template.ts';
import type { PipelineConfig } from '../../types/pipeline.ts';

const { Text } = Typography;

export interface WorkflowState {
  phase: WorkflowPhase;
  jobId: string | null;
  message: string;
  error: string | null;
  modelUrl: string | null;
  parsedParams: ParamDefinition[] | null;
  stepPath: string | null;
  templateName: string | null;
}

export interface GenerateWorkflowProps {
  state: WorkflowState;
  onPhaseChange: (state: WorkflowState) => void;
}

const PHASE_STEP_MAP: Record<WorkflowPhase, number> = {
  idle: -1,
  parsing: 0,
  confirming: 1,
  generating: 2,
  refining: 3,
  completed: 4,
  failed: -1,
};

const STEP_ITEMS = [
  { title: '意图解析', icon: <ToolOutlined /> },
  { title: '参数确认', icon: <EditOutlined /> },
  { title: '模型生成', icon: <RocketOutlined /> },
  { title: '模型优化', icon: <LoadingOutlined /> },
  { title: '完成', icon: <CheckCircleOutlined /> },
];

/** Hook: manage generate workflow via SSE. */
export function useGenerateWorkflow() {
  const [state, setState] = useState<WorkflowState>({
    phase: 'idle',
    jobId: null,
    message: '',
    error: null,
    modelUrl: null,
    parsedParams: null,
    stepPath: null,
    templateName: null,
  });
  const abortRef = useRef<AbortController | null>(null);

  const startTextGenerate = useCallback(async (text: string, pipelineConfig?: PipelineConfig) => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setState({
      phase: 'parsing',
      jobId: null,
      message: '正在解析意图…',
      error: null,
      modelUrl: null,
      parsedParams: null,
      stepPath: null,
      templateName: null,
    });

    try {
      const resp = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, pipeline_config: pipelineConfig ?? {} }),
        signal: abort.signal,
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('No response body');

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const jsonStr = line.slice(5).trim();
            if (!jsonStr) continue;
            try {
              const evt = JSON.parse(jsonStr);
              handleSSEEvent(evt, setState);
            } catch {
              // skip malformed JSON
            }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return;
      setState((prev) => ({
        ...prev,
        phase: 'failed',
        error: (err as Error).message || '连接失败',
      }));
    }
  }, []);

  const confirmParams = useCallback(
    async (confirmedParams: Record<string, number>) => {
      if (!state.jobId) return;

      const abort = new AbortController();
      abortRef.current = abort;

      setState((prev) => ({
        ...prev,
        phase: 'generating',
        message: '参数已确认，正在生成…',
      }));

      try {
        const resp = await fetch(`/api/generate/${state.jobId}/confirm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmed_params: confirmedParams }),
          signal: abort.signal,
        });

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }

        const reader = resp.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) throw new Error('No response body');

        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data:')) {
              const jsonStr = line.slice(5).trim();
              if (!jsonStr) continue;
              try {
                const evt = JSON.parse(jsonStr);
                handleSSEEvent(evt, setState);
              } catch {
                // skip malformed JSON
              }
            }
          }
        }
      } catch (err: unknown) {
        if ((err as Error).name === 'AbortError') return;
        setState((prev) => ({
          ...prev,
          phase: 'failed',
          error: (err as Error).message || '确认失败',
        }));
      }
    },
    [state.jobId],
  );

  const startDrawingGenerate = useCallback(async (file: File, pipelineConfig?: PipelineConfig) => {
    abortRef.current?.abort();

    setState({
      phase: 'generating',
      jobId: null,
      message: '正在分析图纸…',
      error: null,
      modelUrl: null,
      parsedParams: null,
      stepPath: null,
      templateName: null,
    });

    const formData = new FormData();
    formData.append('image', file);
    formData.append('pipeline_config', JSON.stringify(pipelineConfig ?? {}));

    try {
      const resp = await fetch('/api/generate/drawing', {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('No response body');

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          if (buffer.trim()) {
            for (const line of buffer.split('\n')) {
              if (line.startsWith('data:')) {
                const jsonStr = line.slice(5).trim();
                if (!jsonStr) continue;
                try {
                  const evt = JSON.parse(jsonStr);
                  handleSSEEvent(evt, setState);
                } catch { /* skip */ }
              }
            }
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const jsonStr = line.slice(5).trim();
            if (!jsonStr) continue;
            try {
              const evt = JSON.parse(jsonStr);
              handleSSEEvent(evt, setState);
            } catch {
              // skip malformed JSON
            }
          }
        }
      }
    } catch (err: unknown) {
      setState((prev) => ({
        ...prev,
        phase: 'failed',
        error: (err as Error).message || '图纸生成失败',
      }));
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState({
      phase: 'idle',
      jobId: null,
      message: '',
      error: null,
      modelUrl: null,
      parsedParams: null,
      stepPath: null,
      templateName: null,
    });
  }, []);

  return {
    state,
    startTextGenerate,
    startDrawingGenerate,
    confirmParams,
    reset,
  };
}

function handleSSEEvent(
  evt: Record<string, unknown>,
  setState: React.Dispatch<React.SetStateAction<WorkflowState>>,
) {
  const jobId = evt.job_id as string;
  const status = evt.status as string;
  const message = (evt.message as string) || '';

  switch (status) {
    case 'created':
      setState((prev) => ({ ...prev, jobId, phase: 'parsing', message }));
      break;
    case 'intent_parsed':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'confirming',
        message,
        parsedParams: (evt.params as ParamDefinition[] | undefined) ?? null,
        templateName: (evt.template_name as string | undefined) ?? null,
      }));
      break;
    case 'awaiting_confirmation':
      setState((prev) => ({ ...prev, jobId, phase: 'confirming', message }));
      break;
    case 'generating':
      setState((prev) => ({ ...prev, jobId, phase: 'generating', message }));
      break;
    case 'refining':
      setState((prev) => ({ ...prev, jobId, phase: 'refining', message }));
      break;
    case 'completed':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'completed',
        message,
        modelUrl: (evt.model_url as string | undefined) ?? null,
        stepPath: (evt.step_path as string | undefined) ?? null,
      }));
      break;
    case 'failed':
    case 'validation_failed':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'failed',
        error: message || '生成失败',
      }));
      break;
  }
}

/** Visual workflow progress indicator. */
export default function GenerateWorkflow({ state }: GenerateWorkflowProps) {
  const currentStep = PHASE_STEP_MAP[state.phase];

  if (state.phase === 'idle') return null;

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Steps
        size="small"
        current={currentStep}
        status={state.phase === 'failed' ? 'error' : 'process'}
        items={STEP_ITEMS.map((item, idx) => ({
          ...item,
          status:
            idx < currentStep
              ? 'finish'
              : idx === currentStep
                ? state.phase === 'failed'
                  ? 'error'
                  : 'process'
                : 'wait',
        }))}
      />

      {state.message && (
        <div style={{ marginTop: 12, textAlign: 'center' }}>
          {state.phase !== 'completed' && state.phase !== 'failed' && (
            <Spin size="small" style={{ marginRight: 8 }} />
          )}
          <Text type="secondary">{state.message}</Text>
        </div>
      )}

      {state.phase === 'failed' && state.error && (
        <Alert
          type="error"
          message={state.error}
          showIcon
          style={{ marginTop: 12 }}
        />
      )}

      {state.phase === 'completed' && (
        <Result
          status="success"
          title="生成完成"
          subTitle={state.message}
          style={{ padding: '16px 0' }}
        />
      )}
    </Card>
  );
}
