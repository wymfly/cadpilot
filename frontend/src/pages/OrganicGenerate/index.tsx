import { useState } from 'react';
import { Row, Col, Card, Button, Typography, Descriptions, Tag } from 'antd';
import { RocketOutlined, ReloadOutlined, CheckOutlined } from '@ant-design/icons';
import { useOrganicWorkflowContext } from '../../contexts/OrganicWorkflowContext.tsx';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import OrganicInput from './OrganicInput.tsx';
import ConstraintForm from './ConstraintForm.tsx';
import QualitySelector from './QualitySelector.tsx';
import OrganicWorkflowProgress from './OrganicWorkflow.tsx';
import MeshStatsCard from './MeshStatsCard.tsx';
import OrganicDownloadButtons from './OrganicDownloadButtons.tsx';
import PrintReport from '../../components/PrintReport/index.tsx';

const { Title, Text } = Typography;

export default function OrganicGenerate() {
  const {
    workflow,
    startGenerate,
    confirmJob,
    reset,
    constraints,
    setConstraints,
    qualityMode,
    setQualityMode,
    provider,
    setProvider,
  } = useOrganicWorkflowContext();

  const dt = useDesignTokens();
  const [prompt, setPrompt] = useState('');
  const [imageFile, setImageFile] = useState<File | null>(null);

  const isConfirming = workflow.phase === 'awaiting_confirmation';
  const isRunning =
    workflow.phase !== 'idle' &&
    workflow.phase !== 'completed' &&
    workflow.phase !== 'failed' &&
    !isConfirming;

  const handleGenerate = async () => {
    if (!prompt.trim() && !imageFile) return;
    await startGenerate({
      prompt: prompt.trim(),
      imageFile,
      constraints,
      qualityMode,
      provider,
    });
  };

  const handleReset = () => {
    reset();
    setPrompt('');
    setImageFile(null);
  };

  const canGenerate = (prompt.trim().length > 0 || imageFile !== null) && !isRunning;

  return (
    <div>
      <Title level={3}>创意雕塑</Title>

      <Row gutter={24}>
        <Col xs={24} lg={10}>
          <Card title="创意输入" size="small" style={{ marginBottom: 16 }}>
            <OrganicInput
              prompt={prompt}
              onPromptChange={setPrompt}
              imageFile={imageFile}
              onImageChange={setImageFile}
              disabled={isRunning}
            />
          </Card>

          <Card title="工程约束" size="small" style={{ marginBottom: 16 }}>
            <ConstraintForm
              constraints={constraints}
              onChange={setConstraints}
              disabled={isRunning}
            />
          </Card>

          <Card title="生成设置" size="small" style={{ marginBottom: 16 }}>
            <QualitySelector
              qualityMode={qualityMode}
              onQualityChange={setQualityMode}
              provider={provider}
              onProviderChange={setProvider}
              disabled={isRunning}
            />
          </Card>

          {isConfirming && workflow.organicSpec && (
            <Card
              title="AI 分析结果"
              size="small"
              style={{ marginBottom: 16, borderColor: dt.color.warning }}
              extra={
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  onClick={() => confirmJob()}
                >
                  确认生成
                </Button>
              }
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="英文描述">
                  {workflow.organicSpec.prompt_en}
                </Descriptions.Item>
                <Descriptions.Item label="形状类别">
                  <Tag color="blue">{workflow.organicSpec.shape_category}</Tag>
                </Descriptions.Item>
                {workflow.organicSpec.final_bounding_box && (
                  <Descriptions.Item label="包围盒 (mm)">
                    {workflow.organicSpec.final_bounding_box.join(' × ')}
                  </Descriptions.Item>
                )}
                {workflow.organicSpec.engineering_cuts.length > 0 && (
                  <Descriptions.Item label="工程切割">
                    {workflow.organicSpec.engineering_cuts.map((cut, i) => (
                      <Tag key={i}>{cut.type}</Tag>
                    ))}
                  </Descriptions.Item>
                )}
                <Descriptions.Item label="质量模式">
                  {workflow.organicSpec.quality_mode}
                </Descriptions.Item>
              </Descriptions>
              <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
                确认以上分析结果后将开始 3D 模型生成
              </Text>
            </Card>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              size="large"
              onClick={handleGenerate}
              disabled={!canGenerate}
              loading={isRunning}
              style={{ flex: 1 }}
            >
              生成
            </Button>
            {workflow.phase !== 'idle' && (
              <Button
                icon={<ReloadOutlined />}
                size="large"
                onClick={handleReset}
                disabled={isRunning && !isConfirming}
              >
                重新开始
              </Button>
            )}
          </div>
        </Col>

        <Col xs={24} lg={14}>
          <OrganicWorkflowProgress state={workflow} />

          <Card
            size="small"
            title="3D 预览"
            style={{ marginBottom: 16 }}
            bodyStyle={{ padding: 0, height: 450 }}
          >
            <Viewer3D modelUrl={workflow.modelUrl} />
          </Card>

          {workflow.meshStats && <MeshStatsCard stats={workflow.meshStats} />}

          {workflow.printability && (
            <div style={{ marginBottom: 16 }}>
              <PrintReport results={workflow.printability} />
            </div>
          )}

          {workflow.phase === 'completed' && (
            <OrganicDownloadButtons
              modelUrl={workflow.modelUrl}
              stlUrl={workflow.stlUrl}
              threemfUrl={workflow.threemfUrl}
            />
          )}
        </Col>
      </Row>
    </div>
  );
}
