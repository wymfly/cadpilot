import { useDesignTokens } from '../../theme/useDesignTokens.ts';

export default function LaserScanLine() {
  const dt = useDesignTokens();

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        overflow: 'hidden',
        zIndex: 2,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          height: 2,
          background: `linear-gradient(90deg, transparent, ${dt.color.primary}, transparent)`,
          boxShadow: `0 0 8px ${dt.color.primary}, 0 0 24px ${dt.color.primary}40`,
          animation: 'laserScan 3s ease-in-out infinite',
          opacity: 0.6,
        }}
      />
    </div>
  );
}
