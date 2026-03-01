import { memo } from 'react';
import { BaseEdge, getStraightPath, type EdgeProps } from '@xyflow/react';

function AnimatedEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, style, ...rest } = props;
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
        stroke: props.animated ? '#1677ff' : '#d9d9d9',
      }}
    />
  );
}

export default memo(AnimatedEdge);
