import { useEffect, useRef, useState } from 'react';
import { Alert, Typography } from 'antd';
import { validatePipelineConfig } from '../../services/api.ts';
import type { NodeLevelConfig, PipelineValidateResponse } from '../../types/pipeline.ts';

const { Text } = Typography;

interface ValidationBannerProps {
  config: Record<string, NodeLevelConfig>;
  inputType?: string | null;
}

export default function ValidationBanner({ config, inputType }: ValidationBannerProps) {
  const [result, setResult] = useState<PipelineValidateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    // Clear previous timer
    if (timerRef.current) clearTimeout(timerRef.current);

    // Debounce 300ms
    timerRef.current = setTimeout(() => {
      // Cancel in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      validatePipelineConfig(inputType ?? null, config, controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) {
            setResult(data);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted && err?.name !== 'AbortError') {
            setResult({ valid: false, error: '验证请求失败' });
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, [config, inputType]);

  if (!result && !loading) return null;

  if (loading) {
    return <Alert type="info" message="验证中..." showIcon style={{ marginBottom: 8 }} />;
  }

  if (!result) return null;

  if (result.valid) {
    return (
      <Alert
        type="success"
        showIcon
        style={{ marginBottom: 8 }}
        message={
          <Text>
            有效 — {result.node_count} 个节点，拓扑: {result.topology?.join(' → ')}
          </Text>
        }
      />
    );
  }

  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 8 }}
      message={<Text>无效 — {result.error}</Text>}
    />
  );
}
