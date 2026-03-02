import { useEffect, useRef } from 'react';
import { Tag } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import TerminalCursor from '../decorative/TerminalCursor.tsx';
import type { JobEvent } from '../../hooks/useJobEvents.ts';

const STATUS_COLORS: Record<string, string> = {
  created: 'default',
  analyzing: 'processing',
  intent_parsed: 'blue',
  awaiting_confirmation: 'warning',
  awaiting_drawing_confirmation: 'warning',
  generating: 'processing',
  refining: 'processing',
  completed: 'success',
  failed: 'error',
};

export interface PipelineLogProps {
  events: JobEvent[];
  maxHeight?: number;
}

export default function PipelineLog({
  events,
  maxHeight = 400,
}: PipelineLogProps) {
  const dt = useDesignTokens();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          padding: 24,
        }}
      >
        <TerminalCursor message="Waiting for pipeline events..." />
      </div>
    );
  }

  return (
    <div
      style={{
        maxHeight,
        overflow: 'auto',
        fontFamily: dt.typography.fontMono,
        fontSize: 12,
        lineHeight: 1.8,
        background: dt.color.surface0,
        borderRadius: dt.radius.sm,
        padding: '8px 12px',
      }}
    >
      {events.map((event, idx) => {
        const color = STATUS_COLORS[event.status] ?? 'default';
        const time = new Date().toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });
        return (
          <div
            key={idx}
            style={{
              padding: '2px 0',
              borderBottom: `1px solid ${dt.color.border}`,
            }}
          >
            <span style={{ fontSize: 11, marginRight: 6, color: dt.color.textTertiary }}>
              {time}
            </span>
            <Tag
              color={color}
              style={{ fontSize: 11, lineHeight: '16px', marginRight: 6 }}
            >
              {event.stage ?? event.status}
            </Tag>
            <span style={{ fontSize: 12, color: dt.color.textPrimary }}>{event.message}</span>
            {event.progress != null && (
              <span style={{ fontSize: 11, marginLeft: 4, color: dt.color.textSecondary }}>
                ({Math.round(event.progress * 100)}%)
              </span>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
