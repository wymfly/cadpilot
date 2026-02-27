import { useState } from 'react';
import { Row, Col, Card, Button, Typography } from 'antd';
import { RocketOutlined, ReloadOutlined } from '@ant-design/icons';
import { useOrganicWorkflowContext } from '../../contexts/OrganicWorkflowContext.tsx';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import OrganicInput from './OrganicInput.tsx';
import ConstraintForm from './ConstraintForm.tsx';
import QualitySelector from './QualitySelector.tsx';
import OrganicWorkflowProgress from './OrganicWorkflow.tsx';
import MeshStatsCard from './MeshStatsCard.tsx';
import OrganicDownloadButtons from './OrganicDownloadButtons.tsx';

const { Title } = Typography;

export default function OrganicGenerate() {
  const {
    workflow,
    startGenerate,
    startImageGenerate,
    reset,
    constraints,
    setConstraints,
    qualityMode,
    setQualityMode,
    provider,
    setProvider,
  } = useOrganicWorkflowContext();

  const [prompt, setPrompt] = useState('');
  const [imageFile, setImageFile] = useState<File | null>(null);

  const isRunning = workflow.phase !== 'idle' && workflow.phase !== 'completed' && workflow.phase !== 'failed';

  const handleGenerate = async () => {
    if (imageFile) {
      await startImageGenerate(imageFile, constraints, qualityMode, provider);
    } else if (prompt.trim()) {
      await startGenerate({
        prompt: prompt.trim(),
        constraints,
        quality_mode: qualityMode,
        provider,
      });
    }
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
                disabled={isRunning}
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

          {workflow.phase === 'completed' && (
            <OrganicDownloadButtons stlUrl={workflow.stlUrl} threemfUrl={workflow.threemfUrl} />
          )}
        </Col>
      </Row>
    </div>
  );
}
