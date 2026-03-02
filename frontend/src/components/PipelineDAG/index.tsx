import { useState, useCallback, useMemo, useEffect } from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

import NodeCard from './NodeCard.tsx';
import AnimatedEdge from './AnimatedEdge.tsx';
import NodeInspector from './NodeInspector.tsx';
import type { NodeInspectorData } from './NodeInspector.tsx';
import type { NodeStatus } from './NodeCard.tsx';
import { getFilteredTopology } from './topology.ts';
import { getPipelineNodes } from '../../services/api.ts';
import type { PipelineNodeDescriptor } from '../../types/pipeline.ts';
import type { JobEvent } from '../../hooks/useJobEvents.ts';

export interface NodeState {
  status: NodeStatus;
  elapsedMs?: number;
  reasoning?: Record<string, string> | null;
  outputsSummary?: Record<string, unknown> | null;
  error?: string;
}

const nodeTypes = { pipelineNode: NodeCard };
const edgeTypes = { animatedEdge: AnimatedEdge };

interface PipelineDAGProps {
  inputType: string | null;
  events: JobEvent[];
}

export default function PipelineDAG({ inputType, events }: PipelineDAGProps) {
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorData, setInspectorData] = useState<NodeInspectorData | null>(null);
  const [descriptors, setDescriptors] = useState<PipelineNodeDescriptor[] | undefined>(undefined);

  // Fetch node descriptors from API (fallback to hardcoded on failure)
  useEffect(() => {
    getPipelineNodes()
      .then(setDescriptors)
      .catch(() => {
        // Use hardcoded fallback topology
      });
  }, []);

  // Derive node states from events using explicit _eventType
  const nodeStates = useMemo(() => {
    const states = new Map<string, NodeState>();

    for (const evt of events) {
      const evtAny = evt as Record<string, unknown>;
      const eventType = evtAny._eventType as string | undefined;
      const node = evtAny.node as string | undefined;
      if (!node || !eventType) continue;

      switch (eventType) {
        case 'node.started':
          if (!states.has(node) || states.get(node)!.status === 'pending') {
            states.set(node, { status: 'running' });
          }
          break;
        case 'node.completed':
          states.set(node, {
            status: 'completed',
            elapsedMs: evtAny.elapsed_ms as number,
            reasoning: evtAny.reasoning as Record<string, string> | null,
            outputsSummary: evtAny.outputs_summary as Record<string, unknown>,
          });
          break;
        case 'node.failed':
          states.set(node, {
            status: 'failed',
            elapsedMs: evtAny.elapsed_ms as number,
            error: evtAny.error as string,
          });
          break;
      }
    }

    return states;
  }, [events]);

  const { nodes: baseNodes, edges: baseEdges } = useMemo(
    () => getFilteredTopology(inputType, descriptors),
    [inputType, descriptors],
  );

  // Enrich nodes with status data + active strategy from events
  const nodes = useMemo(
    () =>
      baseNodes.map((n) => {
        const state = nodeStates.get(n.id);
        return {
          ...n,
          data: {
            ...n.data,
            status: state?.status || 'pending',
            elapsedMs: state?.elapsedMs,
          },
        };
      }),
    [baseNodes, nodeStates],
  );

  // Animate edges whose source is completed
  const edges = useMemo(
    () =>
      baseEdges.map((e) => {
        const sourceState = nodeStates.get(e.source);
        return {
          ...e,
          animated: sourceState?.status === 'completed',
        };
      }),
    [baseEdges, nodeStates],
  );

  const handleNodeClick = useCallback(
    (_: unknown, node: { id: string; data: Record<string, unknown> }) => {
      const state = nodeStates.get(node.id);
      if (!state || state.status === 'pending') return;

      setInspectorData({
        nodeId: node.id,
        label: (node.data.label as string) ?? node.id,
        status: state.status,
        elapsedMs: state.elapsedMs,
        reasoning: state.reasoning,
        outputsSummary: state.outputsSummary,
        error: state.error,
      });
      setInspectorOpen(true);
    },
    [nodeStates],
  );

  const dt = useDesignTokens();

  return (
    <div style={{ height: 500, border: `1px solid ${dt.color.border}`, borderRadius: dt.radius.md }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
        style={{ background: dt.color.surface0 }}
      >
        <Background color={dt.color.border} />
        <Controls />
      </ReactFlow>

      <NodeInspector
        open={inspectorOpen}
        data={inspectorData}
        onClose={() => setInspectorOpen(false)}
      />
    </div>
  );
}
