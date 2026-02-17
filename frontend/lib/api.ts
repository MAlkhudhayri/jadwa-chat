import { Collection, Conversation, UploadResponse, StreamEvent, Source } from "@/types";

const API_BASE = "/api";

// ─── Collections ──────────────────────────────────────

export async function fetchCollections(): Promise<Collection[]> {
  const res = await fetch(`${API_BASE}/collections/`);
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error("Failed to create collection");
  return res.json();
}

export async function deleteCollection(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${name}`, {
    method: "DELETE",
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
    headers: { "Content-Type": "application/json" },
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
  const res = await fetch(`${API_BASE}/chat/conversations${params}`);
  if (!res.ok) throw new Error("Failed to fetch conversations");
  return res.json();
}

export async function fetchConversation(conversationId: string) {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}`);
  if (!res.ok) throw new Error("Failed to fetch conversation");
  return res.json();
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete conversation");
}

// ─── Health ───────────────────────────────────────────

export async function checkHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Backend unreachable");
  return res.json();
}

