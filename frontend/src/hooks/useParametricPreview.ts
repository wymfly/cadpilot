import { useState, useRef, useCallback, useEffect } from 'react';
import { previewParametric } from '../services/api.ts';

export interface UseParametricPreviewOptions {
  templateName: string | null;
  params: Record<string, number>;
  debounceMs?: number;
  timeoutMs?: number;
  enabled?: boolean;
}

export interface PreviewStatus {
  loading: boolean;
  error: string | null;
  timedOut: boolean;
  available: boolean;
}

export interface UseParametricPreviewResult {
  previewUrl: string | null;
  loading: boolean;
  error: string | null;
  status: PreviewStatus;
  retry: () => void;
}

/**
 * Debounced parametric preview hook.
 * Triggers a preview API call when params change, with configurable debounce.
 * Keeps the last successful URL visible during loading/error states.
 * Returns the GLB URL for the Viewer3D component.
 */
export function useParametricPreview({
  templateName,
  params,
  debounceMs = 500,
  timeoutMs = 10000,
  enabled = true,
}: UseParametricPreviewOptions): UseParametricPreviewResult {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [hasSucceeded, setHasSucceeded] = useState(false);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestParamsRef = useRef<{ name: string; params: Record<string, number> } | null>(null);

  const clearTimers = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const fetchPreview = useCallback(
    async (name: string, p: Record<string, number>) => {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);
      setTimedOut(false);

      // Start timeout timer
      timeoutRef.current = setTimeout(() => {
        if (!abort.signal.aborted) {
          setTimedOut(true);
          abort.abort();
        }
      }, timeoutMs);

      try {
        const result = await previewParametric(name, p, abort.signal);
        if (!abort.signal.aborted) {
          setPreviewUrl(result.glb_url);
          setHasSucceeded(true);
        }
      } catch (err: unknown) {
        if (
          (err as Error).name === 'AbortError' ||
          (err as Error).name === 'CanceledError'
        ) {
          return;
        }
        if (!abort.signal.aborted) {
          setError((err as Error).message || '预览加载失败');
        }
      } finally {
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }
        if (!abort.signal.aborted) {
          setLoading(false);
        }
      }
    },
    [timeoutMs],
  );

  // Stabilize params reference via JSON serialization
  const paramsKey = JSON.stringify(params);

  useEffect(() => {
    if (!enabled || !templateName || Object.keys(params).length === 0) {
      return;
    }

    latestParamsRef.current = { name: templateName, params };

    clearTimers();

    timerRef.current = setTimeout(() => {
      fetchPreview(templateName, params);
    }, debounceMs);

    return () => {
      clearTimers();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateName, paramsKey, debounceMs, enabled, fetchPreview, clearTimers]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      clearTimers();
    };
  }, [clearTimers]);

  // Manual retry using latest params
  const retry = useCallback(() => {
    if (latestParamsRef.current) {
      fetchPreview(latestParamsRef.current.name, latestParamsRef.current.params);
    }
  }, [fetchPreview]);

  const status: PreviewStatus = {
    loading,
    error,
    timedOut,
    available: hasSucceeded,
  };

  return { previewUrl, loading, error, status, retry };
}
