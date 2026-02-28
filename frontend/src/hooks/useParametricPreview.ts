import { useState, useRef, useCallback, useEffect } from 'react';
import { previewParametric } from '../services/api.ts';

interface UseParametricPreviewOptions {
  templateName: string | null;
  params: Record<string, number>;
  debounceMs?: number;
  enabled?: boolean;
}

interface UseParametricPreviewResult {
  previewUrl: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * Debounced parametric preview hook.
 * Triggers a preview API call when params change, with configurable debounce.
 * Returns the GLB URL for the Viewer3D component.
 */
export function useParametricPreview({
  templateName,
  params,
  debounceMs = 300,
  enabled = true,
}: UseParametricPreviewOptions): UseParametricPreviewResult {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchPreview = useCallback(
    async (name: string, p: Record<string, number>) => {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);

      try {
        const result = await previewParametric(name, p, abort.signal);
        if (!abort.signal.aborted) {
          setPreviewUrl(result.glb_url);
        }
      } catch (err: unknown) {
        if ((err as Error).name === 'AbortError' || (err as Error).name === 'CanceledError') return;
        if (!abort.signal.aborted) {
          setError((err as Error).message || '预览加载失败');
        }
      } finally {
        if (!abort.signal.aborted) {
          setLoading(false);
        }
      }
    },
    [],
  );

  // Stabilize params reference via JSON serialization
  const paramsKey = JSON.stringify(params);

  useEffect(() => {
    if (!enabled || !templateName || Object.keys(params).length === 0) {
      return;
    }

    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    timerRef.current = setTimeout(() => {
      fetchPreview(templateName, params);
    }, debounceMs);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateName, paramsKey, debounceMs, enabled, fetchPreview]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return { previewUrl, loading, error };
}
