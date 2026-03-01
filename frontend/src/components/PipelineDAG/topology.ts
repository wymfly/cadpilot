import type { Node, Edge } from '@xyflow/react';

export interface PipelineNode {
  id: string;
  label: string;
  group: 'init' | 'analysis' | 'hitl' | 'generation' | 'postprocess' | 'final';
}

export interface PipelineTopology {
  nodes: PipelineNode[];
  edges: Array<{ source: string; target: string }>;
}

const ALL_NODES: PipelineNode[] = [
  { id: 'create_job', label: '创建任务', group: 'init' },
  { id: 'analyze_intent', label: '意图解析', group: 'analysis' },
  { id: 'analyze_vision', label: '图纸分析', group: 'analysis' },
  { id: 'analyze_organic', label: '有机分析', group: 'analysis' },
  { id: 'confirm_with_user', label: '用户确认', group: 'hitl' },
  { id: 'generate_step_text', label: '文本生成', group: 'generation' },
  { id: 'generate_step_drawing', label: '图纸生成', group: 'generation' },
  { id: 'generate_organic_mesh', label: '有机生成', group: 'generation' },
  { id: 'postprocess_organic', label: '有机后处理', group: 'generation' },
  { id: 'convert_preview', label: 'GLB 预览', group: 'postprocess' },
  { id: 'check_printability', label: '可打印性检查', group: 'postprocess' },
  { id: 'finalize', label: '完成', group: 'final' },
];

const ALL_EDGES = [
  { source: 'create_job', target: 'analyze_intent' },
  { source: 'create_job', target: 'analyze_vision' },
  { source: 'create_job', target: 'analyze_organic' },
  { source: 'analyze_intent', target: 'confirm_with_user' },
  { source: 'analyze_vision', target: 'confirm_with_user' },
  { source: 'analyze_organic', target: 'confirm_with_user' },
  { source: 'confirm_with_user', target: 'generate_step_text' },
  { source: 'confirm_with_user', target: 'generate_step_drawing' },
  { source: 'confirm_with_user', target: 'generate_organic_mesh' },
  { source: 'generate_step_text', target: 'convert_preview' },
  { source: 'generate_step_drawing', target: 'convert_preview' },
  { source: 'generate_organic_mesh', target: 'postprocess_organic' },
  { source: 'postprocess_organic', target: 'finalize' },
  { source: 'convert_preview', target: 'check_printability' },
  { source: 'check_printability', target: 'finalize' },
];

/** Path-specific node IDs */
const PATH_NODES: Record<string, string[]> = {
  text: [
    'create_job', 'analyze_intent', 'confirm_with_user',
    'generate_step_text', 'convert_preview', 'check_printability', 'finalize',
  ],
  drawing: [
    'create_job', 'analyze_vision', 'confirm_with_user',
    'generate_step_drawing', 'convert_preview', 'check_printability', 'finalize',
  ],
  organic: [
    'create_job', 'analyze_organic', 'confirm_with_user',
    'generate_organic_mesh', 'postprocess_organic', 'finalize',
  ],
};

/**
 * Layout row assignments for the full (unfiltered) DAG.
 * Branching nodes at the same depth get different x positions.
 */
const FULL_LAYOUT: Record<string, { x: number; y: number }> = {
  create_job:            { x: 250, y: 0 },
  // Analysis branch: three parallel paths
  analyze_intent:        { x: 80,  y: 100 },
  analyze_vision:        { x: 250, y: 100 },
  analyze_organic:       { x: 420, y: 100 },
  confirm_with_user:     { x: 250, y: 200 },
  // Generation branch: three parallel paths
  generate_step_text:    { x: 80,  y: 300 },
  generate_step_drawing: { x: 250, y: 300 },
  generate_organic_mesh: { x: 420, y: 300 },
  // Post-processing
  postprocess_organic:   { x: 420, y: 400 },
  convert_preview:       { x: 165, y: 400 },
  check_printability:    { x: 165, y: 500 },
  finalize:              { x: 250, y: 600 },
};

/** Filter topology by input_type, return ReactFlow-compatible nodes and edges. */
export function getFilteredTopology(
  inputType: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const visibleIds = new Set(
    inputType && PATH_NODES[inputType]
      ? PATH_NODES[inputType]
      : ALL_NODES.map((n) => n.id),
  );

  const filteredNodes = ALL_NODES.filter((n) => visibleIds.has(n.id));
  const filteredEdges = ALL_EDGES.filter(
    (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
  );

  // For single-path (filtered), use simple vertical layout centered at x=200
  // For full DAG (unfiltered), use branch-aware positions
  const isSinglePath = inputType != null && PATH_NODES[inputType] != null;

  const nodes: Node[] = filteredNodes.map((n, i) => ({
    id: n.id,
    type: 'pipelineNode',
    position: isSinglePath
      ? { x: 200, y: i * 100 }
      : FULL_LAYOUT[n.id] ?? { x: 200, y: i * 100 },
    data: { label: n.label, group: n.group },
  }));

  const edges: Edge[] = filteredEdges.map((e) => ({
    id: `${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    type: 'animatedEdge',
    animated: false,
  }));

  return { nodes, edges };
}
