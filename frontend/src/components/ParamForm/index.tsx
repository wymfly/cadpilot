import { useMemo } from 'react';
import { Form, Button, Card, Space, Typography, Tag, Empty } from 'antd';
import { CheckOutlined, UndoOutlined, EyeOutlined, EyeInvisibleOutlined, SyncOutlined } from '@ant-design/icons';
import ParamField from './ParamField.tsx';
import ConstraintAlert from './ConstraintAlert.tsx';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import type { ParamDefinition } from '../../types/template.ts';
import type { ParamRecommendation, ConstraintViolation } from '../../types/standard.ts';
import type { PreviewStatus } from '../../hooks/useParametricPreview.ts';

const { Title, Text } = Typography;

export interface ParamFormProps {
  params: ParamDefinition[];
  values: Record<string, number | string | boolean>;
  recommendations?: ParamRecommendation[];
  violations?: ConstraintViolation[];
  previewStatus?: PreviewStatus;
  onRetryPreview?: () => void;
  onChange: (name: string, value: number | string | boolean) => void;
  onConfirm: () => void;
  onReset?: () => void;
  loading?: boolean;
  title?: string;
}

export default function ParamForm({
  params,
  values,
  recommendations = [],
  violations = [],
  previewStatus,
  onRetryPreview,
  onChange,
  onConfirm,
  onReset,
  loading = false,
  title = '参数确认',
}: ParamFormProps) {
  const dt = useDesignTokens();
  const recMap = useMemo(() => {
    const map: Record<string, ParamRecommendation> = {};
    for (const r of recommendations) {
      map[r.param_name] = r;
    }
    return map;
  }, [recommendations]);

  const hasErrors = violations.some((v) => v.severity === 'error');

  if (params.length === 0) {
    return (
      <Card size="small" title={title}>
        <Empty description="暂无参数定义" />
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={
        <Space>
          <Title level={5} style={{ margin: 0 }}>
            {title}
          </Title>
          <Tag>{params.length} 个参数</Tag>
          {recommendations.length > 0 && (
            <Tag color="blue">{recommendations.length} 个推荐</Tag>
          )}
          {previewStatus && (
            previewStatus.loading ? (
              <Tag icon={<SyncOutlined spin />} color="processing">实时预览</Tag>
            ) : previewStatus.timedOut ? (
              <Tag
                icon={<EyeInvisibleOutlined />}
                color="warning"
                style={{ cursor: onRetryPreview ? 'pointer' : undefined }}
                onClick={onRetryPreview}
              >
                预览超时{onRetryPreview ? ' (点击重试)' : ''}
              </Tag>
            ) : previewStatus.error ? (
              <Tag
                icon={<EyeInvisibleOutlined />}
                color="error"
                style={{ cursor: onRetryPreview ? 'pointer' : undefined }}
                onClick={onRetryPreview}
              >
                预览不可用
              </Tag>
            ) : previewStatus.available ? (
              <Tag icon={<EyeOutlined />} color="success">实时预览</Tag>
            ) : null
          )}
        </Space>
      }
    >
      <ConstraintAlert violations={violations} />

      <Form layout="vertical">
        {params.map((param) => (
          <ParamField
            key={param.name}
            param={param}
            value={values[param.name]}
            recommendation={recMap[param.name]}
            onChange={onChange}
          />
        ))}
      </Form>

      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 8,
          marginTop: 16,
          paddingTop: 16,
          borderTop: `1px solid ${dt.color.border}`,
        }}
      >
        {onReset && (
          <Button icon={<UndoOutlined />} onClick={onReset}>
            重置
          </Button>
        )}
        <Button
          type="primary"
          icon={<CheckOutlined />}
          onClick={onConfirm}
          loading={loading}
          disabled={hasErrors}
        >
          确认参数
        </Button>
        {hasErrors && (
          <Text type="danger" style={{ alignSelf: 'center' }}>
            请先修正错误
          </Text>
        )}
      </div>
    </Card>
  );
}

export { default as ParamField } from './ParamField.tsx';
export { default as ParamSlider } from './ParamSlider.tsx';
export { default as ConstraintAlert } from './ConstraintAlert.tsx';
