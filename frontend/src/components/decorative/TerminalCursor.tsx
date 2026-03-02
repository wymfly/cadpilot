import { useDesignTokens } from '../../theme/useDesignTokens.ts';

interface TerminalCursorProps {
  message?: string;
}

export default function TerminalCursor({ message = 'Ready' }: TerminalCursorProps) {
  const dt = useDesignTokens();

  return (
    <div
      style={{
        fontFamily: dt.typography.fontMono,
        fontSize: dt.typography.data.size,
        color: dt.color.textSecondary,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
      }}
    >
      <span style={{ color: dt.color.primary }}>&gt;</span>
      <span>{message}</span>
      <span
        style={{
          display: 'inline-block',
          width: 7,
          height: 14,
          background: dt.color.primary,
          animation: 'terminalBlink 1s step-end infinite',
          marginLeft: 2,
        }}
      />
    </div>
  );
}
