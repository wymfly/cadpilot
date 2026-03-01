import { useState, useCallback, useEffect, useMemo } from 'react';
import { Typography, Row, Col, Button, Space } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import PipelineConfigBar from '../../components/PipelineConfigBar/index.tsx';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import ParamForm from '../../components/ParamForm/index.tsx';
import PipelinePanel from '../../components/PipelinePanel/index.tsx';
import ChatInput from './ChatInput.tsx';
import DownloadButtons from './DownloadButtons.tsx';
import GenerateWorkflow from './GenerateWorkflow.tsx';
import DrawingSpecReview from './DrawingSpecReview.tsx';
import PrintReport from '../../components/PrintReport/index.tsx';
import { useGenerateWorkflowContext } from '../../contexts/GenerateWorkflowContext.tsx';
import { useParametricPreview } from '../../hooks/useParametricPreview.ts';
import { useJobEvents } from '../../hooks/useJobEvents.ts';

const { Title, Paragraph } = Typography;

export default function Generate() {
  const {
    workflow,
    startTextGenerate,
    startDrawingGenerate,
    confirmParams,
    confirmDrawingSpec,
    reset,
    pipelineConfig,
    setPipelineConfig,
  } = useGenerateWorkflowContext();

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

  // Extract numeric params for preview
  const numericParams = useMemo(() => {
    const result: Record<string, number> = {};
    for (const [k, v] of Object.entries(paramValues)) {
      if (typeof v === 'number') result[k] = v;
    }
    return result;
  }, [paramValues]);

  // Debounced parametric preview during confirming phase
  const { previewUrl } = useParametricPreview({
    templateName: workflow.templateName,
    params: numericParams,
    enabled: workflow.phase === 'confirming' && !!workflow.templateName,
  });

  // Use preview URL during confirming, otherwise use workflow model URL
  const viewerModelUrl = previewUrl ?? workflow.modelUrl;

  // M3: DAG events for PipelinePanel
  const { events: dagEvents } = useJobEvents({ jobId: workflow.jobId });
  const dagInputType = workflow.inputType;

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
              onSendText={(text) => startTextGenerate(text, pipelineConfig)}
              onSendImage={(file) => startDrawingGenerate(file, pipelineConfig)}
              disabled={isInputDisabled}
              loading={workflow.phase === 'parsing'}
            />

            {/* Workflow progress + DAG */}
            <PipelinePanel
              progressView={<GenerateWorkflow state={workflow} onPhaseChange={() => {}} />}
              inputType={dagInputType}
              events={dagEvents}
            />

            {/* Drawing spec review (shown during drawing_review phase) */}
            {workflow.phase === 'drawing_review' && workflow.drawingSpec && (
              <DrawingSpecReview
                drawingSpec={workflow.drawingSpec}
                onConfirm={confirmDrawingSpec}
                onCancel={reset}
              />
            )}

            {/* Download buttons (shown when generation is complete) */}
            {workflow.phase === 'completed' && workflow.jobId && (
              <DownloadButtons jobId={workflow.jobId} />
            )}

            {/* Printability report (shown when completed with printability data) */}
            {workflow.phase === 'completed' && workflow.printability && (
              <PrintReport results={workflow.printability} />
            )}

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
            <PipelineConfigBar value={pipelineConfig} onChange={setPipelineConfig} />
          </Space>
        </Col>

        {/* Right panel: 3D preview */}
        <Col xs={24} lg={14}>
          <div style={{ height: 600 }}>
            <Viewer3D modelUrl={viewerModelUrl} />
          </div>
        </Col>
      </Row>
    </div>
  );
}
