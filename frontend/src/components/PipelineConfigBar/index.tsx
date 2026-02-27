import { useState, useEffect, useCallback } from 'react';
import { Card, Collapse } from 'antd';
import PresetSelector from './PresetSelector.tsx';
import CustomPanel from './CustomPanel.tsx';
import { getTooltips } from '../../services/api.ts';
import type { PipelineConfig, TooltipSpec } from '../../types/pipeline.ts';

const PRESET_CONFIGS: Record<string, Omit<PipelineConfig, 'preset'>> = {
  fast: {
    ocr_assist: false,
    two_pass_analysis: false,
    multi_model_voting: false,
    self_consistency_runs: 1,
    best_of_n: 1,
    rag_enabled: false,
    api_whitelist: true,
    ast_pre_check: true,
    volume_check: false,
    topology_check: false,
    cross_section_check: false,
    max_refinements: 1,
    multi_view_render: false,
    structured_feedback: true,
    rollback_on_degrade: true,
    contour_overlay: false,
    printability_check: false,
    output_formats: ['step'],
  },
  balanced: {
    ocr_assist: false,
    two_pass_analysis: false,
    multi_model_voting: false,
    self_consistency_runs: 1,
    best_of_n: 3,
    rag_enabled: true,
    api_whitelist: true,
    ast_pre_check: true,
    volume_check: true,
    topology_check: true,
    cross_section_check: false,
    max_refinements: 3,
    multi_view_render: true,
    structured_feedback: true,
    rollback_on_degrade: true,
    contour_overlay: false,
    printability_check: false,
    output_formats: ['step', 'stl'],
  },
  precise: {
    ocr_assist: true,
    two_pass_analysis: true,
    multi_model_voting: true,
    self_consistency_runs: 3,
    best_of_n: 5,
    rag_enabled: true,
    api_whitelist: true,
    ast_pre_check: true,
    volume_check: true,
    topology_check: true,
    cross_section_check: true,
    max_refinements: 3,
    multi_view_render: true,
    structured_feedback: true,
    rollback_on_degrade: true,
    contour_overlay: true,
    printability_check: true,
    output_formats: ['step', 'stl', '3mf'],
  },
};

const DEFAULT_CONFIG: PipelineConfig = {
  preset: 'balanced',
  ...PRESET_CONFIGS['balanced'],
};

// Fallback tooltips when API is not available
const FALLBACK_TOOLTIPS: Record<string, TooltipSpec> = {
  best_of_n: {
    title: '多路生成 (Best-of-N)',
    description: '生成 N 份候选代码并择优',
    when_to_use: '复杂零件推荐',
    cost: '耗时 xN, Token xN',
    default: 'balanced: N=3',
  },
  rag_enabled: {
    title: 'RAG 增强',
    description: '检索相似零件代码作为参考示例',
    when_to_use: '知识库有相似零件时效果好',
    cost: '增加约 1s 检索时间',
    default: 'balanced: 开启',
  },
  ocr_assist: {
    title: 'OCR 辅助',
    description: 'OCR 提取图纸标注文字辅助分析',
    when_to_use: '图纸标注密集、VL 易遗漏时',
    cost: '增加约 2s',
    default: 'precise: 开启',
  },
  two_pass_analysis: {
    title: '两阶段分析',
    description: '先全局分析再局部细化',
    when_to_use: '图纸内容复杂时',
    cost: '分析时间 x2',
    default: 'precise: 开启',
  },
  multi_model_voting: {
    title: '多模型投票',
    description: '多个 VL 模型分别分析并投票',
    when_to_use: '对分析结果要求极高时',
    cost: '分析时间 x模型数',
    default: 'precise: 开启',
  },
  self_consistency_runs: {
    title: 'Self-Consistency',
    description: '同一模型多次推理取一致结果',
    when_to_use: '分析结果不稳定时',
    cost: '分析时间 xN',
    default: 'precise: N=3',
  },
  api_whitelist: {
    title: 'API 白名单',
    description: '限制使用已验证的 CadQuery API',
    when_to_use: '减少无效 API 调用',
    cost: '无额外开销',
    default: '默认开启',
  },
  ast_pre_check: {
    title: 'AST 预检查',
    description: '执行前静态分析代码结构',
    when_to_use: '提前发现语法错误',
    cost: '无额外开销',
    default: '默认开启',
  },
  volume_check: {
    title: '体积验证',
    description: '对比理论体积与实际体积',
    when_to_use: '检测尺寸偏差',
    cost: '增加约 0.5s',
    default: 'balanced: 开启',
  },
  topology_check: {
    title: '拓扑验证',
    description: '验证模型拓扑完整性',
    when_to_use: '检测非流形、开孔等问题',
    cost: '增加约 0.5s',
    default: 'balanced: 开启',
  },
  cross_section_check: {
    title: '截面分析',
    description: '生成截面视图验证内部结构',
    when_to_use: '含内部特征的复杂零件',
    cost: '增加约 1s',
    default: 'precise: 开启',
  },
  max_refinements: {
    title: '最大修复轮数',
    description: '模型不合格时自动修复的最大次数',
    when_to_use: '复杂零件可能需要更多轮修复',
    cost: '每轮约 10-30s',
    default: 'balanced: 3 轮',
  },
  multi_view_render: {
    title: '多视角渲染',
    description: '生成多角度渲染图用于 VL 比对',
    when_to_use: '提高修复判断准确度',
    cost: '增加约 2s',
    default: 'balanced: 开启',
  },
  structured_feedback: {
    title: '结构化反馈',
    description: 'VL 以 JSON 格式输出具体问题列表',
    when_to_use: '提高修复针对性',
    cost: '无额外开销',
    default: '默认开启',
  },
  rollback_on_degrade: {
    title: '退化回滚',
    description: '修复后质量下降时自动回滚',
    when_to_use: '防止越修越差',
    cost: '无额外开销',
    default: '默认开启',
  },
  contour_overlay: {
    title: '轮廓叠加',
    description: '将渲染轮廓叠加到原图比对',
    when_to_use: '精确比对外形匹配度',
    cost: '增加约 1s',
    default: 'precise: 开启',
  },
  printability_check: {
    title: '可打印性检查',
    description: '检查模型是否满足 3D 打印要求',
    when_to_use: '需要 3D 打印输出时',
    cost: '增加约 2s',
    default: 'precise: 开启',
  },
};

export interface PipelineConfigBarProps {
  value?: PipelineConfig;
  onChange?: (config: PipelineConfig) => void;
}

export { DEFAULT_CONFIG };

export default function PipelineConfigBar({ value, onChange: onExternalChange }: PipelineConfigBarProps = {}) {
  const [internalConfig, setInternalConfig] = useState<PipelineConfig>(DEFAULT_CONFIG);
  const config = value ?? internalConfig;
  const [tooltips, setTooltips] = useState<Record<string, TooltipSpec>>(FALLBACK_TOOLTIPS);
  const [customExpanded, setCustomExpanded] = useState(false);

  useEffect(() => {
    getTooltips()
      .then(setTooltips)
      .catch(() => {
        // Use fallback tooltips when API is unavailable
      });
  }, []);

  const updateConfig = useCallback((newConfig: PipelineConfig) => {
    setInternalConfig(newConfig);
    onExternalChange?.(newConfig);
  }, [onExternalChange]);

  const handlePresetChange = useCallback((preset: PipelineConfig['preset']) => {
    if (preset === 'custom') {
      const newConfig = { ...config, preset: 'custom' as const };
      updateConfig(newConfig);
      setCustomExpanded(true);
    } else {
      const presetConfig = PRESET_CONFIGS[preset];
      if (presetConfig) {
        updateConfig({ preset, ...presetConfig });
      }
      setCustomExpanded(false);
    }
  }, [config, updateConfig]);

  const handleCustomChange = useCallback((patch: Partial<PipelineConfig>) => {
    updateConfig({ ...config, ...patch, preset: 'custom' as const });
  }, [config, updateConfig]);

  return (
    <Card size="small" title="管道配置" style={{ marginBottom: 16 }}>
      <PresetSelector value={config.preset} onChange={handlePresetChange} />
      <Collapse
        activeKey={customExpanded ? ['custom'] : []}
        onChange={(keys) => setCustomExpanded(keys.includes('custom'))}
        ghost
        style={{ marginTop: 12 }}
        items={[
          {
            key: 'custom',
            label: '自定义高级选项',
            children: (
              <CustomPanel
                config={config}
                tooltips={tooltips}
                onChange={handleCustomChange}
              />
            ),
          },
        ]}
      />
    </Card>
  );
}
