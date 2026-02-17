export interface Source {
  content: string;
  metadata: Record<string, any>;
  score: number;
  page?: number;
  filename?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  isStreaming?: boolean;
}

export interface Collection {
  name: string;
  document_count: number;
  description?: string;
}

export interface Conversation {
  conversation_id: string;
  title: string;
  collection_name: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatRequest {
  message: string;
  collection_name: string;
  conversation_id?: string;
}

export interface UploadResponse {
  filename: string;
  collection_name: string;
  chunks_created: number;
  status: string;
}

export interface StreamEvent {
  type: "sources" | "token" | "done" | "error";
  content?: string;
  sources?: Source[];
  conversation_id?: string;
  collection_name?: string;
  message?: string;
}

