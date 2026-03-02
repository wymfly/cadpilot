import { useDesignTokens } from '../../theme/useDesignTokens.ts';

interface CrosshairProps {
  size?: number;
  pulse?: boolean;
}

export default function Crosshair({ size = 12, pulse = false }: CrosshairProps) {
  const dt = useDesignTokens();
  const color = dt.color.border;

  const cornerStyle = (position: Record<string, number | string>): React.CSSProperties => ({
    position: 'absolute',
    width: size,
    height: size,
    opacity: 0.3,
    animation: pulse ? 'crosshairPulse 2s ease-in-out infinite' : undefined,
    ...position,
  });

  const borderWidth = 1;

  return (
    <>
      {/* Top-left */}
      <span
        style={cornerStyle({ top: 0, left: 0, borderTop: `${borderWidth}px solid ${color}`, borderLeft: `${borderWidth}px solid ${color}` })}
      />
      {/* Top-right */}
      <span
        style={cornerStyle({ top: 0, right: 0, borderTop: `${borderWidth}px solid ${color}`, borderRight: `${borderWidth}px solid ${color}` })}
      />
      {/* Bottom-left */}
      <span
        style={cornerStyle({ bottom: 0, left: 0, borderBottom: `${borderWidth}px solid ${color}`, borderLeft: `${borderWidth}px solid ${color}` })}
      />
      {/* Bottom-right */}
      <span
        style={cornerStyle({ bottom: 0, right: 0, borderBottom: `${borderWidth}px solid ${color}`, borderRight: `${borderWidth}px solid ${color}` })}
      />
    </>
  );
}
