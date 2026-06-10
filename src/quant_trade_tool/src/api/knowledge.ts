import { getApiBase } from "@/config";
import { http } from "./http";

export interface KbCitation {
  doc_id: string;
  title: string;
  chunk_id: string;
  snippet: string;
  path?: string | null;
  score?: number;
}

export interface KbDocument {
  id: string;
  title: string;
  source: string;
  path?: string | null;
  mime?: string | null;
  tags: string[];
  updated_at: string;
  chunk_count: number;
  content_hash?: string | null;
}

export interface KbCursorApiCheck {
  ok: boolean;
  error?: string;
  user_email?: string;
  api_key_name?: string;
  status_code?: number;
}

export interface KbStatus {
  doc_count: number;
  chunk_count: number;
  session_count: number;
  last_sync_at?: string | null;
  cursor_configured: boolean;
  cursor_api_available: boolean;
  cursor_api_check?: KbCursorApiCheck;
  cursor_sdk_installed?: boolean;
  cursor_sdk_check?: KbCursorApiCheck;
  cursor_sdk_available?: boolean;
  kb_agent_backend?: string;
  cursor_backend?: string;
  embedding_model: string;
  openai_configured: boolean;
  fallback_openai: boolean;
}

export interface KbChatResponse {
  session_id: string;
  answer: string;
  citations: KbCitation[];
  disclaimer: string;
  backend?: string;
  backend_error?: string;
}

export interface KbMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  citations: KbCitation[];
  created_at: string;
}

export interface KbSession {
  id: string;
  agent_id?: string | null;
  title?: string | null;
  created_at: string;
  updated_at: string;
}

export const knowledgeApi = {
  status() {
    return http.get<KbStatus>("/kb/status");
  },

  documents(params?: { tag?: string; page?: number; page_size?: number }) {
    return http.get<{ total: number; items: KbDocument[] }>("/kb/documents", { params });
  },

  deleteDocument(id: string) {
    return http.delete<{ deleted: boolean; id: string }>(`/kb/documents/${id}`);
  },

  syncProject(dataDir = "data", docsDir = "docs") {
    return http.post<{ ingested: number; skipped: number; last_sync_at?: string }>(
      "/kb/sync-project",
      null,
      { params: { data_dir: dataDir, docs_dir: docsDir } },
    );
  },

  upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    return http.post<{ ok: boolean; doc_id?: string; warning?: string }>("/kb/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  chat(body: { message: string; session_id?: string; top_k?: number; tags?: string[] }) {
    const message = body.message.trim();
    if (!message) {
      return Promise.reject(new Error("请输入问题后再发送"));
    }
    const payload: Record<string, unknown> = { message, stream: false };
    if (body.session_id) payload.session_id = body.session_id;
    if (body.top_k != null) payload.top_k = body.top_k;
    if (body.tags?.length) payload.tags = body.tags;
    return http.post<KbChatResponse>("/kb/chat", payload);
  },

  sessions(limit = 30) {
    return http.get<{ items: KbSession[]; count: number }>("/kb/chat/sessions", {
      params: { limit },
    });
  },

  sessionDetail(id: string) {
    return http.get<{ session: KbSession; messages: KbMessage[] }>(`/kb/chat/sessions/${id}`);
  },

  async chatStream(
    body: { message: string; session_id?: string; top_k?: number },
    onMeta: (meta: {
      session_id: string;
      citations: KbCitation[];
      disclaimer: string;
      backend?: string;
    }) => void,
    onToken: (text: string) => void,
    onDone: (sessionId: string) => void,
    onError: (detail: string) => void,
    onBackend?: (backend: string) => void,
  ) {
    const base = getApiBase();
    const url = `${base ? `${base}/api/v1` : "/api/v1"}/kb/chat`;
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, stream: true }),
    });
    if (!resp.ok) {
      const err = await resp.text();
      onError(err.slice(0, 500));
      return;
    }
    const reader = resp.body?.getReader();
    if (!reader) {
      onError("stream unavailable");
      return;
    }
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const lines = part.split("\n");
        let event = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) data = line.slice(5).trim();
        }
        if (!data) continue;
        try {
          const parsed = JSON.parse(data);
          if (event === "meta") onMeta(parsed);
          else if (event === "token") onToken(parsed.text || "");
          else if (event === "backend") onBackend?.(parsed.backend || "");
          else if (event === "done") onDone(parsed.session_id);
          else if (event === "error") onError(parsed.detail || data);
        } catch {
          /* ignore malformed */
        }
      }
    }
  },
};
