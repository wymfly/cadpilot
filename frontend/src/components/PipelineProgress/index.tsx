import { useState, useEffect } from 'react';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import type { WorkflowPhase } from '../../types/generate.ts';

interface StageInfo {
  title: string;
}

const STAGES: StageInfo[] = [
  { title: '意图解析' },
  { title: '参数确认' },
  { title: '模型生成' },
  { title: '模型优化' },
  { title: '质量检查' },
  { title: '完成' },
];

const PHASE_TO_STEP: Record<WorkflowPhase, number> = {
  idle: -1,
  parsing: 0,
  confirming: 1,
  drawing_review: 1,
  generating: 2,
  refining: 3,
  completed: 5,
  failed: -1,
};

export interface PipelineProgressProps {
  phase: WorkflowPhase;
  message?: string;
  startTime?: number;
  error?: string | null;
  /** 父组件管理的"最后活跃步骤"，防止组件 remount 时丢失 */
  lastActiveStep?: number;
  onActiveStepChange?: (step: number) => void;
}

export default function PipelineProgress({
  phase,
  message,
  startTime,
  error,
  lastActiveStep: externalLastStep,
  onActiveStepChange,
}: PipelineProgressProps) {
  const dt = useDesignTokens();

  // 本地 fallback：无外部管理时自行维护
  const [internalLastStep, setInternalLastStep] = useState(0);
  const lastActiveStep = externalLastStep ?? internalLastStep;
  const rawStep = PHASE_TO_STEP[phase];
  const currentStep = rawStep >= 0 ? rawStep : lastActiveStep;

  useEffect(() => {
    if (rawStep >= 0 && phase !== 'failed') {
      setInternalLastStep(rawStep);
      onActiveStepChange?.(rawStep);
    }
  }, [rawStep, phase, onActiveStepChange]);

  const [elapsed, setElapsed] = useState<string | null>(null);
  useEffect(() => {
    if (!startTime) {
      setElapsed(null);
      return;
    }
    const tick = () => {
      const seconds = Math.floor((Date.now() - startTime) / 1000);
      setElapsed(seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startTime]);

  if (phase === 'idle') return null;

  const getStepStatus = (idx: number): 'completed' | 'running' | 'failed' | 'pending' => {
    if (idx < currentStep) return 'completed';
    if (idx === currentStep) return phase === 'failed' ? 'failed' : 'running';
    return 'pending';
  };

  const getLedColor = (status: 'completed' | 'running' | 'failed' | 'pending') => {
    switch (status) {
      case 'completed': return dt.color.success;
      case 'running': return dt.color.primary;
      case 'failed': return dt.color.error;
      case 'pending': return 'transparent';
    }
  };

  const getLedBorder = (status: 'completed' | 'running' | 'failed' | 'pending') => {
    if (status === 'pending') return `1px solid ${dt.color.border}`;
    return '1px solid transparent';
  };

  return (
    <div style={{ fontFamily: dt.typography.fontMono }}>
      {/* LED step indicators */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {STAGES.map((stage, idx) => {
          const status = getStepStatus(idx);
          const isLast = idx === STAGES.length - 1;
          return (
            <div key={idx}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                {/* LED block */}
                <div
                  style={{
                    width: 12,
                    height: 12,
                    marginTop: 2,
                    flexShrink: 0,
                    borderRadius: 2,
                    background: getLedColor(status),
                    border: getLedBorder(status),
                    animation: status === 'running' ? 'ledPulse 1.5s ease-in-out infinite' : undefined,
                  }}
                />
                {/* Label + description */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: status === 'running' ? 600 : 400,
                      color: status === 'pending' ? dt.color.textTertiary : dt.color.textPrimary,
                      lineHeight: '16px',
                    }}
                  >
                    {stage.title}
                  </div>
                  {idx === currentStep && (message || elapsed) && (
                    <div style={{ marginTop: 2 }}>
                      {message && (
                        <div style={{ fontSize: 11, color: dt.color.textSecondary }}>{message}</div>
                      )}
                      {elapsed && (
                        <div style={{ fontSize: 11, color: dt.color.textTertiary }}>
                          已用时 {elapsed}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              {/* Connector line */}
              {!isLast && (
                <div
                  style={{
                    width: 1,
                    height: idx === currentStep && (message || elapsed) ? 12 : 8,
                    marginLeft: 5.5,
                    background: idx < currentStep ? dt.color.success : dt.color.border,
                  }}
                />
              )}
            </div>
          );
        })}
      </div>

      {phase === 'failed' && error && (
        <div
          style={{
            marginTop: 8,
            padding: '8px 12px',
            borderRadius: dt.radius.sm,
            background: dt.isDark ? 'rgba(255,51,51,0.1)' : 'rgba(229,48,48,0.06)',
            border: `1px solid ${dt.color.error}`,
          }}
        >
          <span style={{ fontSize: 12, color: dt.color.error }}>
            {error}
          </span>
        </div>
      )}

      {/* LED pulse animation — uses globalStyles.css ledPulse */}
    </div>
  );
}
