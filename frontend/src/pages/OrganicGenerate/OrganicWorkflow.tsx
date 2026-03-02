import { useState, useCallback, useRef } from 'react';
import { Steps, Alert, Spin, Result, Card, Typography, Progress } from 'antd';
import {
  SearchOutlined,
  EditOutlined,
  RocketOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  MinusCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type {
  OrganicWorkflowState,
  OrganicPhase,
  OrganicConstraints,
  OrganicSpec,
  MeshStats,
  PostProcessStepInfo,
  PostProcessStepStatus,
} from '../../types/organic.ts';
import { useDesignTokens, type ResolvedColors } from '../../theme/useDesignTokens.ts';

const { Text } = Typography;

const PHASE_STEP_MAP: Record<OrganicPhase, number> = {
  idle: -1,
  created: 0,
  analyzing: 0,
  awaiting_confirmation: 1,
  generating: 2,
  post_processing: 3,
  completed: 4,
  failed: -1,
};

const STEP_ITEMS = [
  { title: '分析', icon: <SearchOutlined /> },
  { title: '确认', icon: <EditOutlined /> },
  { title: '生成', icon: <RocketOutlined /> },
  { title: '后处理', icon: <ToolOutlined /> },
  { title: '完成', icon: <CheckCircleOutlined /> },
];

const DEFAULT_POST_PROCESS_STEPS: PostProcessStepInfo[] = [
  { step: 'load', label: '网格加载', status: 'pending' },
  { step: 'repair', label: '网格修复', status: 'pending' },
  { step: 'scale', label: '网格缩放', status: 'pending' },
  { step: 'boolean', label: '布尔切割', status: 'pending' },
  { step: 'validate', label: '质量验证', status: 'pending' },
];

const INITIAL_STATE: OrganicWorkflowState = {
  phase: 'idle',
  jobId: null,
  message: '',
  progress: 0,
  error: null,
  organicSpec: null,
  modelUrl: null,
  stlUrl: null,
  threemfUrl: null,
  meshStats: null,
  postProcessStep: null,
  postProcessSteps: DEFAULT_POST_PROCESS_STEPS.map((s) => ({ ...s })),
  warnings: [],
  printability: null,
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
    case 'organic_spec_ready':
      setState((prev) => ({
        ...prev,
        jobId,
        organicSpec: (evt.organic_spec as OrganicSpec) ?? null,
      }));
      break;
    case 'awaiting_confirmation':
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'awaiting_confirmation',
        message: '请确认 AI 分析结果',
        progress: 0,
      }));
      break;
    case 'generating':
      setState((prev) => ({ ...prev, jobId, phase: 'generating', message, progress }));
      break;
    case 'post_processing': {
      const step = (evt.step as string) ?? null;
      const stepStatus = (evt.step_status as PostProcessStepStatus) ?? null;
      setState((prev) => ({
        ...prev,
        jobId,
        phase: 'post_processing',
        message,
        progress,
        postProcessStep: step,
        postProcessSteps: step && stepStatus
          ? prev.postProcessSteps.map((s) =>
              s.step === step ? { ...s, status: stepStatus, message } : s
            )
          : prev.postProcessSteps,
      }));
      break;
    }
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
        warnings: (evt.warnings as string[]) ?? [],
        printability: (evt.printability as OrganicWorkflowState['printability']) ?? null,
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
            } catch (e) { console.warn('Failed to parse SSE event:', jsonStr, e); }
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
      postProcessSteps: DEFAULT_POST_PROCESS_STEPS.map((s) => ({ ...s })),
      phase: 'analyzing',
      message: hasImage ? '正在上传参考图片…' : '正在分析创意描述…',
    });

    try {
      let fileId: string | undefined;

      // Upload image first if provided
      if (hasImage) {
        const formData = new FormData();
        formData.append('file', opts.imageFile!);

        const uploadResp = await fetch('/api/v1/jobs/upload-reference', {
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
        input_type: 'organic',
        prompt: opts.prompt || 'Generate from reference image',
        constraints: opts.constraints,
        quality_mode: opts.qualityMode,
        provider: opts.provider,
      };
      if (fileId) body.reference_image = fileId;

      const resp = await fetch('/api/v1/jobs', {
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

  const confirmJob = useCallback(async (overrides?: Record<string, unknown>) => {
    const jobId = state.jobId;
    if (!jobId) return;

    const abort = new AbortController();
    abortRef.current = abort;

    setState((prev) => ({
      ...prev,
      phase: 'generating',
      message: '正在启动生成…',
      progress: 0,
    }));

    try {
      const resp = await fetch(`/api/v1/jobs/${jobId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_spec: overrides || {},
          disclaimer_accepted: true,
        }),
        signal: abort.signal,
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await consumeSSE(resp, setState);
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return;
      setState((prev) => ({
        ...prev,
        phase: 'failed',
        error: (err as Error).message || '确认失败',
      }));
    }
  }, [state.jobId]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL_STATE);
  }, []);

  return { state, startGenerate, confirmJob, reset };
}

// ---------------------------------------------------------------------------
// Post-processing sub-step status icon
// ---------------------------------------------------------------------------

function getStepStatusConfig(c: ResolvedColors): Record<PostProcessStepStatus, {
  icon: React.ReactNode;
  color: string;
}> {
  return {
    pending: { icon: <MinusCircleOutlined />, color: c.border },
    running: { icon: <Spin size="small" />, color: c.primary },
    success: { icon: <CheckCircleOutlined />, color: c.success },
    degraded: { icon: <ExclamationCircleOutlined />, color: c.warning },
    skipped: { icon: <MinusCircleOutlined />, color: c.border },
    failed: { icon: <CloseCircleOutlined />, color: c.error },
  };
}

function PostProcessSubSteps({ steps }: { steps: PostProcessStepInfo[] }) {
  const dt = useDesignTokens();
  const hasAnyActivity = steps.some((s) => s.status !== 'pending');
  if (!hasAnyActivity) return null;

  const statusConfig = getStepStatusConfig(dt.color);

  return (
    <div style={{ marginTop: 12, padding: '8px 12px', background: dt.color.surface2, borderRadius: 6 }}>
      <Text type="secondary" style={{ fontSize: 12, marginBottom: 6, display: 'block' }}>
        后处理详情
      </Text>
      {steps.map((s) => {
        const config = statusConfig[s.status];
        return (
          <div
            key={s.step}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '3px 0',
              color: s.status === 'pending' ? dt.color.textTertiary : undefined,
            }}
          >
            <span style={{ color: config.color, fontSize: 14, display: 'flex', alignItems: 'center' }}>
              {config.icon}
            </span>
            <Text
              style={{
                fontSize: 13,
                color: s.status === 'pending' ? dt.color.textTertiary : undefined,
              }}
            >
              {s.label}
            </Text>
            {s.status === 'degraded' && s.message && (
              <Text type="warning" style={{ fontSize: 12 }}>({s.message})</Text>
            )}
            {s.status === 'skipped' && s.message && (
              <Text type="secondary" style={{ fontSize: 12 }}>({s.message})</Text>
            )}
            {s.status === 'failed' && s.message && (
              <Text type="danger" style={{ fontSize: 12 }}>({s.message})</Text>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main progress component
// ---------------------------------------------------------------------------

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

      {state.message && state.phase !== 'completed' && state.phase !== 'failed' && state.phase !== 'awaiting_confirmation' && (
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <Spin size="small" style={{ marginRight: 8 }} />
          <Text type="secondary">{state.message}</Text>
        </div>
      )}

      {state.phase === 'awaiting_confirmation' && (
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <Text type="warning">AI 已完成分析，请在左侧面板确认后继续生成</Text>
        </div>
      )}

      {(state.phase === 'post_processing' || state.phase === 'completed') && (
        <PostProcessSubSteps steps={state.postProcessSteps} />
      )}

      {state.phase === 'failed' && state.error && (
        <Alert type="error" message={state.error} showIcon style={{ marginTop: 12 }} />
      )}

      {state.phase === 'completed' && (
        <>
          <Result
            status="success"
            title="生成完成"
            subTitle={state.message}
            style={{ padding: '16px 0' }}
          />
          {state.warnings.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message="处理过程中的注意事项"
              description={
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {state.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              }
              style={{ marginTop: 0 }}
            />
          )}
        </>
      )}
    </Card>
  );
}
