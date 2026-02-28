import { useEffect, useRef, useCallback, useState } from 'react';
import type { JobStatus } from '../types/generate.ts';

/** SSE 事件载荷 */
export interface JobEvent {
  job_id: string;
  status: JobStatus;
  stage?: string;
  message: string;
  progress?: number;
  [key: string]: unknown;
}

interface UseJobEventsOptions {
  jobId: string | null;
  onEvent?: (event: JobEvent) => void;
  onComplete?: (event: JobEvent) => void;
  onError?: (event: JobEvent) => void;
}

interface UseJobEventsResult {
  events: JobEvent[];
  connected: boolean;
  disconnect: () => void;
}

const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed']);

/**
 * 订阅 Job SSE 事件流。
 * 连接 `GET /api/v1/jobs/{id}/events`，返回实时事件列表。
 * 当 Job 到达终态时自动断开。
 */
export function useJobEvents({
  jobId,
  onEvent,
  onComplete,
  onError,
}: UseJobEventsOptions): UseJobEventsResult {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  // 用 ref 保持回调最新引用
  const onEventRef = useRef(onEvent);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onEventRef.current = onEvent;
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  });

  const closeSource = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    closeSource();
    setConnected(false);
  }, [closeSource]);

  useEffect(() => {
    setEvents([]);
    setConnected(false);

    if (!jobId) return;

    const url = `/api/v1/jobs/${jobId}/events`;
    const source = new EventSource(url);
    sourceRef.current = source;

    // 用局部 ref 跟踪最后事件状态（避免在 state updater 中产生副作用）
    let lastStatus = '';

    const safeParse = (raw: string): JobEvent | null => {
      try {
        return JSON.parse(raw) as JobEvent;
      } catch {
        return null;
      }
    };

    const handleEvent = (event: JobEvent) => {
      lastStatus = event.status;
      setEvents((prev) => [...prev, event]);
      onEventRef.current?.(event);

      if (event.status === 'completed') {
        onCompleteRef.current?.(event);
        source.close();
        sourceRef.current = null;
        setConnected(false);
      } else if (event.status === 'failed') {
        onErrorRef.current?.(event);
        source.close();
        sourceRef.current = null;
        setConnected(false);
      }
    };

    // 后端使用命名 SSE 事件（event: job.generating 等），
    // EventSource.onmessage 不会捕获命名事件，必须逐一注册。
    const SSE_EVENT_TYPES = [
      'status',
      'progress',
      'job.created',
      'job.intent_analyzed',
      'job.awaiting_confirmation',
      'job.vision_analyzing',
      'job.spec_ready',
      'job.generating',
      'job.completed',
      'job.failed',
    ] as const;

    for (const eventType of SSE_EVENT_TYPES) {
      source.addEventListener(eventType, (e: MessageEvent) => {
        const data = safeParse(e.data);
        if (!data) return;
        // 确保 status 字段与事件类型一致
        if (eventType === 'job.completed' || eventType === 'job.failed') {
          const terminalStatus = eventType === 'job.completed' ? 'completed' : 'failed';
          handleEvent({ ...data, status: terminalStatus });
        } else {
          handleEvent(data);
        }
      });
    }

    // 兜底：捕获未列举的未命名事件
    source.onmessage = (e: MessageEvent) => {
      const data = safeParse(e.data);
      if (!data) return;
      handleEvent(data);
    };

    source.onopen = () => {
      setConnected(true);
    };

    source.onerror = () => {
      // EventSource 会自动重连；如果已到终态则断开
      if (TERMINAL_STATUSES.has(lastStatus)) {
        source.close();
        sourceRef.current = null;
        setConnected(false);
      }
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [jobId]);

  return { events, connected, disconnect };
}
