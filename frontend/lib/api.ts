import { Collection, Conversation, UploadResponse, StreamEvent, Source } from "@/types";

const API_BASE = "/api";

// ─── Auth Header Helper ──────────────────────────────

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("jadwachat_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonAuthHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

// ─── Collections ──────────────────────────────────────

export async function fetchCollections(): Promise<Collection[]> {
  const res = await fetch(`${API_BASE}/collections/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch collections");
  const data = await res.json();
  return data.collections;
}

export async function createCollection(
  name: string,
  description?: string
): Promise<Collection> {
  const res = await fetch(`${API_BASE}/collections/`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error("Failed to create collection");
  return res.json();
}

export async function deleteCollection(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${name}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete collection");
}

// ─── Documents ────────────────────────────────────────

export async function uploadDocument(
  file: File,
  collectionName: string
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("collection_name", collectionName);

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to upload document");
  }
  return res.json();
}

export async function uploadMultipleDocuments(
  files: File[],
  collectionName: string
): Promise<UploadResponse[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("collection_name", collectionName);

  const res = await fetch(`${API_BASE}/documents/upload-multiple`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to upload documents");
  return res.json();
}

// ─── Ask (Orchestrator) ─────────────────────────────────

export interface AskResponse {
  answer: string;
  intent: string;
  series_used: string[];
  tools_called: string[];
  conversation_id: string;
  citations: string;
  sources?: Source[];
}

export async function askQuestion(
  question: string,
  collectionName?: string,
  conversationId?: string
): Promise<AskResponse> {
  const res = await fetch(`${API_BASE}/ask/`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      question,
      collection_name: collectionName || undefined,
      conversation_id: conversationId || undefined,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get answer");
  }

  return res.json();
}

// ─── Streaming Ask (SSE) ──────────────────────────────────

export interface AskStreamCallbacks {
  onMetadata?: (data: { intent: string; series_used: string[]; tools_called: string[]; knowledge_source: string }) => void;
  onSources?: (sources: Source[], conversationId: string) => void;
  onToken?: (token: string) => void;
  onDone?: (data: { conversation_id: string; citations: string }) => void;
  onError?: (message: string) => void;
}

export async function askQuestionStream(
  question: string,
  collectionName: string | undefined,
  conversationId: string | undefined,
  callbacks: AskStreamCallbacks,
): Promise<void> {
  const res = await fetch(`${API_BASE}/ask/stream`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      question,
      collection_name: collectionName || undefined,
      conversation_id: conversationId || undefined,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to get streaming answer");
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        if (!dataStr) continue;

        try {
          const data = JSON.parse(dataStr);

          switch (currentEvent || data.type) {
            case "metadata":
              callbacks.onMetadata?.(data);
              break;
            case "sources":
              callbacks.onSources?.(data.sources || [], data.conversation_id || "");
              break;
            case "token":
              callbacks.onToken?.(data.content || "");
              break;
            case "done":
              callbacks.onDone?.(data);
              break;
            case "error":
              callbacks.onError?.(data.message || "Unknown error");
              break;
          }
        } catch {
          // Skip malformed lines
        }
        currentEvent = "";
      }
    }
  }
}

// ─── Upload (Time Series CSV) ─────────────────────────

export interface TimeSeriesUploadResponse {
  type: "timeseries";
  filename: string;
  source: string;
  series_found: string[];
  rows_inserted: number;
  rows_updated: number;
  rows_skipped: number;
  total: number;
  status: string;
}

export async function uploadTimeSeriesFile(
  file: File,
  collectionName: string,
  source?: string
): Promise<TimeSeriesUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("collection_name", collectionName);
  if (source) formData.append("source", source);

  const res = await fetch(`${API_BASE}/upload/`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to upload file");
  }
  return res.json();
}

// Unified smart upload — auto-routes CSV→SQLite, docs→Qdrant
export async function smartUpload(
  file: File,
  collectionName: string,
): Promise<any> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("collection_name", collectionName);

  const res = await fetch(`${API_BASE}/upload/`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to upload file");
  }
  return res.json();
}

// ─── Conversations ────────────────────────────────────

export async function fetchConversations(
  collectionName?: string
): Promise<Conversation[]> {
  const params = collectionName
    ? `?collection_name=${encodeURIComponent(collectionName)}`
    : "";
  const res = await fetch(`${API_BASE}/chat/conversations${params}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch conversations");
  return res.json();
}

export async function fetchConversation(conversationId: string) {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch conversation");
  return res.json();
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete conversation");
}

// ─── Health ───────────────────────────────────────────

export async function checkHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Backend unreachable");
  return res.json();
}
