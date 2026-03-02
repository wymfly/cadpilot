import { useState, useEffect, useMemo, useCallback } from 'react';
import { Button, Typography, Divider, Empty, Descriptions, Tag } from 'antd';
import { RocketOutlined, ReloadOutlined, CheckOutlined } from '@ant-design/icons';
import { useOutletContext } from 'react-router-dom';
import type { WorkbenchOutletContext } from '../../layouts/WorkbenchLayout.tsx';
import { useOrganicWorkflowContext } from '../../contexts/OrganicWorkflowContext.tsx';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import OrganicInput from '../OrganicGenerate/OrganicInput.tsx';
import ConstraintForm from '../OrganicGenerate/ConstraintForm.tsx';
import QualitySelector from '../OrganicGenerate/QualitySelector.tsx';
import MeshStatsCard from '../OrganicGenerate/MeshStatsCard.tsx';
import OrganicDownloadButtons from '../OrganicGenerate/OrganicDownloadButtons.tsx';
import PipelineProgress from '../../components/PipelineProgress/index.tsx';
import OrganicWorkflowProgress from '../OrganicGenerate/OrganicWorkflow.tsx';
import PrintReport from '../../components/PrintReport/index.tsx';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import type { WorkflowPhase } from '../../types/generate.ts';

const { Text, Title } = Typography;

/** 将 OrganicPhase 映射为通用 WorkflowPhase 用于 PipelineProgress */
function toWorkflowPhase(organicPhase: string): WorkflowPhase {
  switch (organicPhase) {
    case 'idle': return 'idle';
    case 'created':
    case 'analyzing': return 'parsing';
    case 'awaiting_confirmation': return 'parsing';
    case 'generating': return 'generating';
    case 'post_processing': return 'refining';
    case 'completed': return 'completed';
    case 'failed': return 'failed';
    default: return 'idle';
  }
}

export default function OrganicWorkbench() {
  const { setPanels } = useOutletContext<WorkbenchOutletContext>();
  const dt = useDesignTokens();
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

  const [prompt, setPrompt] = useState('');
  const [imageFile, setImageFile] = useState<File | null>(null);

  const isConfirming = workflow.phase === 'awaiting_confirmation';
  const isRunning =
    workflow.phase !== 'idle' &&
    workflow.phase !== 'completed' &&
    workflow.phase !== 'failed' &&
    !isConfirming;

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

      case 'awaiting_confirmation':
        return (
          <div>
            <Title level={5}>AI 分析结果</Title>
            {workflow.organicSpec && (
              <>
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
              </>
            )}
            <Button
              type="primary"
              icon={<CheckOutlined />}
              block
              onClick={() => confirmJob()}
              style={{ marginTop: 16 }}
            >
              确认生成
            </Button>
            <Button
              icon={<ReloadOutlined />}
              block
              onClick={handleReset}
              style={{ marginTop: 8 }}
            >
              重新开始
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
    workflow.organicSpec,
    prompt,
    imageFile,
    constraints,
    qualityMode,
    provider,
    isRunning,
    isConfirming,
    canGenerate,
    handleGenerate,
    handleReset,
    confirmJob,
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
              <ul style={{ paddingLeft: 16, color: dt.color.textSecondary, fontSize: 13 }}>
                <li>流线型花瓶，底部宽顶部窄</li>
                <li>几何风格的桌面摆件</li>
                <li>仿生学结构灯罩</li>
              </ul>
            </div>
          </div>
        );

      case 'created':
      case 'analyzing':
      case 'awaiting_confirmation':
      case 'generating':
      case 'post_processing':
        return (
          <div>
            <Title level={5}>管道日志</Title>
            <OrganicWorkflowProgress state={workflow} />
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
  }, [workflow.phase, workflow.printability, workflow, dt.color.textSecondary]);

  // 注入面板内容到 WorkbenchLayout
  useEffect(() => {
    setPanels({ left: leftPanel, right: rightPanel });
  }, [leftPanel, rightPanel, setPanels]);

  // 中央 3D 预览区
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Viewer3D modelUrl={workflow.modelUrl} darkMode={dt.isDark} />
    </div>
  );
}
