import { memo } from 'react';
import { BaseEdge, getStraightPath, type EdgeProps } from '@xyflow/react';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

function AnimatedEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, style, ...rest } = props;
  const dt = useDesignTokens();
  const [edgePath] = getStraightPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  return (
    <BaseEdge
      {...rest}
      path={edgePath}
      style={{
        ...style,
        strokeWidth: 2,
        stroke: props.animated ? dt.color.primary : dt.color.border,
      }}
    />
  );
}

export default memo(AnimatedEdge);
