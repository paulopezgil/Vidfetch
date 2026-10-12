import type {
  Health,
  HistoryPage,
  InfoResult,
  LibraryResponse,
  OperationType,
  FormatName,
  PlaylistDetail,
  Task,
} from "./types";

const BASE = "/api";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? data);
    } catch {
      // keep statusText
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((res) => handle<T>(res));
}

function get<T>(path: string): Promise<T> {
  return fetch(`${BASE}${path}`).then((res) => handle<T>(res));
}

export function fetchInfo(url: string): Promise<InfoResult> {
  return post<InfoResult>("/info", { url });
}

export function startDownload(payload: {
  url: string;
  operation_type: OperationType;
  format: FormatName;
  embed_subs: boolean;
  playlist_id?: string;
}): Promise<{ task_id: string }> {
  return post<{ task_id: string }>("/download", payload);
}

export function listTasks(): Promise<Task[]> {
  return get<Task[]>("/tasks");
}

export function cancelTask(taskId: string): Promise<{ cancelled: boolean }> {
  return post<{ cancelled: boolean }>(`/tasks/${taskId}/cancel`, {});
}

export function listLibrary(): Promise<LibraryResponse> {
  return get<LibraryResponse>("/downloads");
}

export function getPlaylist(id: string): Promise<PlaylistDetail> {
  return get<PlaylistDetail>(`/playlists/${id}`);
}

export function deletePlaylist(id: string): Promise<{ deleted: boolean }> {
  return fetch(`${BASE}/playlists/${id}`, { method: "DELETE" }).then((res) =>
    handle<{ deleted: boolean }>(res),
  );
}

export function deleteFile(filename: string): Promise<{ deleted: boolean }> {
  return fetch(`${BASE}/file/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  }).then((res) => handle<{ deleted: boolean }>(res));
}

export function rebuildZip(
  id: string,
  force = false,
): Promise<{ zip_path: string; built: boolean }> {
  return post<{ zip_path: string; built: boolean }>(`/playlists/${id}/zip`, {
    force,
  });
}

export function listHistory(params: {
  limit?: number;
  offset?: number;
  status?: string;
  search?: string;
}): Promise<HistoryPage> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  if (params.status) qs.set("status", params.status);
  if (params.search) qs.set("search", params.search);
  return get<HistoryPage>(`/history?${qs.toString()}`);
}

export function getHealth(): Promise<Health> {
  return get<Health>("/health");
}

export function fileUrl(filename: string): string {
  return `${BASE}/file/${encodeURIComponent(filename)}`;
}

/**
 * Subscribe to a task's progress via Server-Sent Events.
 * Returns a cleanup function that closes the stream.
 */
export function streamTask(
  taskId: string,
  onUpdate: (task: Task) => void,
  onDone: () => void,
): () => void {
  const source = new EventSource(`${BASE}/tasks/${taskId}/events`);
  source.onmessage = (event) => {
    try {
      onUpdate(JSON.parse(event.data) as Task);
    } catch {
      // ignore malformed frames
    }
  };
  source.addEventListener("done", () => {
    source.close();
    onDone();
  });
  source.addEventListener("error", () => {
    // EventSource may reconnect automatically; only give up if not connecting.
    if (source.readyState === EventSource.CLOSED) {
      source.close();
      onDone();
    }
  });
  return () => source.close();
}
