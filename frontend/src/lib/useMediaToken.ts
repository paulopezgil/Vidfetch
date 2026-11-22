import { useCallback, useEffect, useRef, useState } from "react";
import type { MediaToken } from "../types/v2";
import { getMediaToken } from "./api";

export interface MediaTokenHandle {
  token: MediaToken | null;
  loading: boolean;
  error: string | null;
  /** Mint a new short-lived token; returns `null` if the request failed. */
  refresh: () => Promise<MediaToken | null>;
}

/**
 * Fetch a signed media token for one asset, keeping only the latest response.
 *
 * Tokens are short-lived, so callers should use `refresh` right before a
 * preview or download rather than relying on the token loaded for a thumbnail.
 */
export function useMediaToken(
  assetId: string | null | undefined,
): MediaTokenHandle {
  const [token, setToken] = useState<MediaToken | null>(null);
  const [loading, setLoading] = useState(Boolean(assetId));
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const refresh = useCallback(async (): Promise<MediaToken | null> => {
    const request = ++requestRef.current;
    if (!assetId) {
      setToken(null);
      setLoading(false);
      return null;
    }

    setLoading(true);
    try {
      const next = await getMediaToken(assetId);
      if (request === requestRef.current) {
        setToken(next);
        setError(null);
      }
      return next;
    } catch (e) {
      if (request === requestRef.current) {
        setError(
          e instanceof Error
            ? e.message
            : "No s’ha pogut obrir el fitxer multimèdia.",
        );
      }
      return null;
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, [assetId]);

  useEffect(() => {
    setToken(null);
    setError(null);
    void refresh();
    return () => {
      // Ignore any response that arrives after this asset was replaced.
      requestRef.current += 1;
    };
  }, [refresh]);

  return { token, loading, error, refresh };
}
