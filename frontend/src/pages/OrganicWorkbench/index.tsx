import { useState, useEffect, useMemo, useCallback } from 'react';
import { Button, Typography, Divider, Empty } from 'antd';
import { RocketOutlined, ReloadOutlined } from '@ant-design/icons';
import { useOutletContext } from 'react-router-dom';
import type { WorkbenchOutletContext } from '../../layouts/WorkbenchLayout.tsx';
import { useOrganicWorkflowContext } from '../../contexts/OrganicWorkflowContext.tsx';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import OrganicInput from '../OrganicGenerate/OrganicInput.tsx';
import ConstraintForm from '../OrganicGenerate/ConstraintForm.tsx';
import QualitySelector from '../OrganicGenerate/QualitySelector.tsx';
import MeshStatsCard from '../OrganicGenerate/MeshStatsCard.tsx';
import OrganicDownloadButtons from '../OrganicGenerate/OrganicDownloadButtons.tsx';
import PipelineProgress from '../../components/PipelineProgress/index.tsx';
import PipelineLog from '../../components/PipelineLog/index.tsx';
import PrintReport from '../../components/PrintReport/index.tsx';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import type { JobEvent } from '../../hooks/useJobEvents.ts';
import type { WorkflowPhase } from '../../types/generate.ts';

const { Text, Title } = Typography;

/** 将 OrganicPhase 映射为通用 WorkflowPhase 用于 PipelineProgress */
function toWorkflowPhase(organicPhase: string): WorkflowPhase {
  switch (organicPhase) {
    case 'idle': return 'idle';
    case 'created':
    case 'analyzing': return 'parsing';
    case 'generating': return 'generating';
    case 'post_processing': return 'refining';
    case 'completed': return 'completed';
    case 'failed': return 'failed';
    default: return 'idle';
  }
}

export default function OrganicWorkbench() {
  const { setPanels } = useOutletContext<WorkbenchOutletContext>();
  const { isDark } = useTheme();
  const {
    workflow,
    startGenerate,
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
  const [sseEvents] = useState<JobEvent[]>([]);

  const isRunning =
    workflow.phase !== 'idle' &&
    workflow.phase !== 'completed' &&
    workflow.phase !== 'failed';

  const canGenerate =
    (prompt.trim().length > 0 || imageFile !== null) && !isRunning;

  const handleGenerate = useCallback(async () => {
    if (!prompt.trim() && !imageFile) return;
    await startGenerate({
      prompt: prompt.trim(),
      imageFile,
      constraints,
      qualityMode,
      provider,
    });
  }, [prompt, imageFile, startGenerate, constraints, qualityMode, provider]);

  const handleReset = useCallback(() => {
    reset();
    setPrompt('');
    setImageFile(null);
  }, [reset]);

  // === 左面板 ===
  const leftPanel = useMemo(() => {
    switch (workflow.phase) {
      case 'idle':
        return (
          <div>
            <OrganicInput
              prompt={prompt}
              onPromptChange={setPrompt}
              imageFile={imageFile}
              onImageChange={setImageFile}
              disabled={isRunning}
            />

            <Divider style={{ margin: '16px 0' }} />

            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              工程约束
            </Text>
            <ConstraintForm
              constraints={constraints}
              onChange={setConstraints}
              disabled={isRunning}
            />

            <Divider style={{ margin: '16px 0' }} />

            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              生成设置
            </Text>
            <QualitySelector
              qualityMode={qualityMode}
              onQualityChange={setQualityMode}
              provider={provider}
              onProviderChange={setProvider}
              disabled={isRunning}
            />

            <Button
              type="primary"
              icon={<RocketOutlined />}
              size="large"
              block
              onClick={handleGenerate}
              disabled={!canGenerate}
              loading={isRunning}
              style={{ marginTop: 16 }}
            >
              生成
            </Button>
          </div>
        );

      case 'created':
      case 'analyzing':
      case 'generating':
      case 'post_processing':
        return (
          <PipelineProgress
            phase={toWorkflowPhase(workflow.phase)}
            message={workflow.message}
          />
        );

      case 'completed':
        return (
          <div>
            <OrganicDownloadButtons
              modelUrl={workflow.modelUrl}
              stlUrl={workflow.stlUrl}
              threemfUrl={workflow.threemfUrl}
            />
            {workflow.meshStats && (
              <div style={{ marginTop: 16 }}>
                <MeshStatsCard stats={workflow.meshStats} />
              </div>
            )}
            <Button
              icon={<ReloadOutlined />}
              block
              onClick={handleReset}
              style={{ marginTop: 16 }}
            >
              重新开始
            </Button>
          </div>
        );

      case 'failed':
        return (
          <div>
            <PipelineProgress
              phase="failed"
              message={workflow.message}
              error={workflow.error}
            />
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={handleReset}
              style={{ marginTop: 16, width: '100%' }}
            >
              重新开始
            </Button>
          </div>
        );

      default:
        return null;
    }
  }, [
    workflow.phase,
    workflow.message,
    workflow.error,
    workflow.modelUrl,
    workflow.stlUrl,
    workflow.threemfUrl,
    workflow.meshStats,
    prompt,
    imageFile,
    constraints,
    qualityMode,
    provider,
    isRunning,
    canGenerate,
    handleGenerate,
    handleReset,
    setConstraints,
    setQualityMode,
    setProvider,
  ]);

  // === 右面板 ===
  const rightPanel = useMemo(() => {
    switch (workflow.phase) {
      case 'idle':
        return (
          <div>
            <Title level={5}>创意雕塑</Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              输入文本描述或上传参考图片，AI 将生成 3D 网格模型。
              支持添加工程约束（尺寸限制、孔位、平底面等）。
            </Text>
            <div style={{ marginTop: 16 }}>
              <Title level={5}>示例</Title>
              <ul style={{ paddingLeft: 16, color: '#666', fontSize: 13 }}>
                <li>流线型花瓶，底部宽顶部窄</li>
                <li>几何风格的桌面摆件</li>
                <li>仿生学结构灯罩</li>
              </ul>
            </div>
          </div>
        );

      case 'created':
      case 'analyzing':
      case 'generating':
      case 'post_processing':
        return (
          <div>
            <Title level={5}>管道日志</Title>
            <PipelineLog events={sseEvents} />
          </div>
        );

      case 'completed':
        return workflow.printability ? (
          <PrintReport results={workflow.printability} />
        ) : (
          <div>
            <Title level={5}>生成完成</Title>
            <Text type="secondary">模型已生成，可在左侧面板下载。</Text>
          </div>
        );

      case 'failed':
        return (
          <Empty
            description="生成失败，请检查输入后重试"
            style={{ marginTop: 40 }}
          />
        );

      default:
        return null;
    }
  }, [workflow.phase, workflow.printability, sseEvents]);

  // 注入面板内容到 WorkbenchLayout
  useEffect(() => {
    setPanels({ left: leftPanel, right: rightPanel });
  }, [leftPanel, rightPanel, setPanels]);

  // 中央 3D 预览区
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Viewer3D modelUrl={workflow.modelUrl} darkMode={isDark} />
    </div>
  );
}
