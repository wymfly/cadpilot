import { useState, useCallback, useEffect } from 'react';
import { Typography, Row, Col, Button, Space } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import PipelineConfigBar from '../../components/PipelineConfigBar/index.tsx';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import ParamForm from '../../components/ParamForm/index.tsx';
import ChatInput from './ChatInput.tsx';
import GenerateWorkflow, { useGenerateWorkflow } from './GenerateWorkflow.tsx';

const { Title, Paragraph } = Typography;

export default function Generate() {
  const {
    state: workflow,
    startTextGenerate,
    startDrawingGenerate,
    confirmParams,
    reset,
  } = useGenerateWorkflow();

  const [paramValues, setParamValues] = useState<
    Record<string, number | string | boolean>
  >({});

  // Initialize param values from parsed params defaults
  useEffect(() => {
    if (workflow.parsedParams) {
      const defaults: Record<string, number | string | boolean> = {};
      for (const p of workflow.parsedParams) {
        if (p.default != null) {
          defaults[p.name] = p.default;
        }
      }
      setParamValues(defaults);
    }
  }, [workflow.parsedParams]);

  const handleParamChange = useCallback(
    (name: string, value: number | string | boolean) => {
      setParamValues((prev) => ({ ...prev, [name]: value }));
    },
    [],
  );

  const handleConfirm = useCallback(() => {
    const numericParams: Record<string, number> = {};
    for (const [k, v] of Object.entries(paramValues)) {
      if (typeof v === 'number') {
        numericParams[k] = v;
      }
    }
    confirmParams(numericParams);
  }, [paramValues, confirmParams]);

  const isInputDisabled =
    workflow.phase !== 'idle' && workflow.phase !== 'completed' && workflow.phase !== 'failed';

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            生成 3D 模型
          </Title>
          <Paragraph type="secondary" style={{ margin: 0 }}>
            描述零件或上传工程图纸，AI 自动生成 3D CAD 模型
          </Paragraph>
        </div>
        {workflow.phase !== 'idle' && (
          <Button icon={<ReloadOutlined />} onClick={reset}>
            重新开始
          </Button>
        )}
      </div>

      <Row gutter={24}>
        {/* Left panel: input + params */}
        <Col xs={24} lg={10}>
          <Space orientation="vertical" style={{ width: '100%' }} size="middle">
            {/* Chat input */}
            <ChatInput
              onSendText={startTextGenerate}
              onSendImage={startDrawingGenerate}
              disabled={isInputDisabled}
              loading={workflow.phase === 'parsing'}
            />

            {/* Workflow progress */}
            <GenerateWorkflow
              state={workflow}
              onPhaseChange={() => {}}
            />

            {/* Parameter confirmation form (shown during confirming phase) */}
            {workflow.phase === 'confirming' && workflow.parsedParams && workflow.parsedParams.length > 0 && (
              <ParamForm
                params={workflow.parsedParams}
                values={paramValues}
                onChange={handleParamChange}
                onConfirm={handleConfirm}
                onReset={() => {
                  if (workflow.parsedParams) {
                    const defaults: Record<string, number | string | boolean> = {};
                    for (const p of workflow.parsedParams) {
                      if (p.default != null) defaults[p.name] = p.default;
                    }
                    setParamValues(defaults);
                  }
                }}
                title="参数确认"
              />
            )}

            {/* Pipeline config (collapsed) */}
            <PipelineConfigBar />
          </Space>
        </Col>

        {/* Right panel: 3D preview */}
        <Col xs={24} lg={14}>
          <div style={{ height: 600 }}>
            <Viewer3D modelUrl={workflow.modelUrl} />
          </div>
        </Col>
      </Row>
    </div>
  );
}
