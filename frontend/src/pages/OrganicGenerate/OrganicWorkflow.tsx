import { useState, useCallback, useRef } from 'react';
import { Steps, Alert, Spin, Result, Card, Typography, Progress } from 'antd';
import {
  SearchOutlined,
  RocketOutlined,
  ToolOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import type {
  OrganicWorkflowState,
  OrganicPhase,
  OrganicGenerateRequest,
  OrganicConstraints,
  MeshStats,
} from '../../types/organic.ts';

const { Text } = Typography;

const PHASE_STEP_MAP: Record<OrganicPhase, number> = {
  idle: -1,
  created: 0,
  analyzing: 0,
  generating: 1,
  post_processing: 2,
  completed: 3,
  failed: -1,
};

const STEP_ITEMS = [
  { title: '分析', icon: <SearchOutlined /> },
  { title: '生成', icon: <RocketOutlined /> },
  { title: '后处理', icon: <ToolOutlined /> },
  { title: '完成', icon: <CheckCircleOutlined /> },
];

const INITIAL_STATE: OrganicWorkflowState = {
  phase: 'idle',
  jobId: null,
  message: '',
  progress: 0,
  error: null,
  modelUrl: null,
  stlUrl: null,
  threemfUrl: null,
  meshStats: null,
  postProcessStep: null,
};

function handleSSEEvent(
  evt: Record<string, unknown>,
  setState: React.Dispatch<React.SetStateAction<OrganicWorkflowState>>,
) {
  const jobId = (evt.job_id as string) ?? null;
  const status = evt.status as string;
  const message = (evt.message as string) || '';
  const progress = (evt.progress as number) ?? 0;

  switch (status) {
    case 'created':
      setState((prev) => ({ ...prev, jobId, phase: 'created', message, progress: 0 }));
      break;
    case 'analyzing':
      setState((prev) => ({ ...prev, jobId, phase: 'analyzing', message, progress }));
      break;
    case 'generating':
      setState((prev) => ({ ...prev, jobId, phase: 'generating', message, progress }));
      break;
    case 'post_processing':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'post_processing',
        message,
        progress,
        postProcessStep: (evt.step as string) ?? null,
      }));
      break;
    case 'completed':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'completed',
        message,
        progress: 1,
        modelUrl: (evt.model_url as string) ?? null,
        stlUrl: (evt.stl_url as string) ?? null,
        threemfUrl: (evt.threemf_url as string) ?? null,
        meshStats: (evt.mesh_stats as MeshStats) ?? null,
      }));
      break;
    case 'failed':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'failed',
        error: message || '生成失败',
      }));
      break;
  }
}

async function consumeSSE(
  resp: Response,
  setState: React.Dispatch<React.SetStateAction<OrganicWorkflowState>>,
) {
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
              handleSSEEvent(JSON.parse(jsonStr), setState);
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
          handleSSEEvent(JSON.parse(jsonStr), setState);
        } catch { /* skip */ }
      }
    }
  }
}

export interface StartGenerateOptions {
  prompt: string;
  imageFile?: File | null;
  constraints: OrganicConstraints;
  qualityMode: string;
  provider: string;
}

export function useOrganicWorkflow() {
  const [state, setState] = useState<OrganicWorkflowState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const startGenerate = useCallback(async (opts: StartGenerateOptions) => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    const hasImage = opts.imageFile != null;

    setState({
      ...INITIAL_STATE,
      phase: 'analyzing',
      message: hasImage ? '正在上传参考图片…' : '正在分析创意描述…',
    });

    try {
      let fileId: string | undefined;

      // Upload image first if provided
      if (hasImage) {
        const formData = new FormData();
        formData.append('file', opts.imageFile!);

        const uploadResp = await fetch('/api/generate/organic/upload', {
          method: 'POST',
          body: formData,
          signal: abort.signal,
        });

        if (!uploadResp.ok) {
          const err = await uploadResp.json().catch(() => ({ detail: `HTTP ${uploadResp.status}` }));
          throw new Error(err.detail || `上传失败: HTTP ${uploadResp.status}`);
        }

        fileId = (await uploadResp.json()).file_id;
        setState((prev) => ({ ...prev, message: '正在分析输入…' }));
      }

      // Start generation with prompt + optional reference_image
      const body: Record<string, unknown> = {
        prompt: opts.prompt || 'Generate from reference image',
        constraints: opts.constraints,
        quality_mode: opts.qualityMode,
        provider: opts.provider,
      };
      if (fileId) body.reference_image = fileId;

      const resp = await fetch('/api/generate/organic', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abort.signal,
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await consumeSSE(resp, setState);
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return;
      setState((prev) => ({
        ...prev,
        phase: 'failed',
        error: (err as Error).message || '连接失败',
      }));
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL_STATE);
  }, []);

  return { state, startGenerate, reset };
}

interface OrganicWorkflowProgressProps {
  state: OrganicWorkflowState;
}

export default function OrganicWorkflowProgress({ state }: OrganicWorkflowProgressProps) {
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

      {state.progress > 0 && state.phase !== 'completed' && state.phase !== 'failed' && (
        <Progress
          percent={Math.round(state.progress * 100)}
          size="small"
          style={{ marginTop: 12 }}
        />
      )}

      {state.message && (
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          {state.phase !== 'completed' && state.phase !== 'failed' && (
            <Spin size="small" style={{ marginRight: 8 }} />
          )}
          <Text type="secondary">{state.message}</Text>
        </div>
      )}

      {state.phase === 'failed' && state.error && (
        <Alert type="error" message={state.error} showIcon style={{ marginTop: 12 }} />
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
