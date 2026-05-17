import type {
  AskRequest, AskResponse, StreamCallbacks,
  LoginResponse, AdminUser,
} from "./types";

const TOKEN_KEY = "auth_token";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token
    ? { "Content-Type": "application/json", Authorization: `Bearer ${token}` }
    : { "Content-Type": "application/json" };
}

// ── Auth API ──────────────────────────────────────────────────────────────────

export async function loginUser(email: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Login failed (${res.status})`);
  }
  return res.json();
}

// ── RAG API ───────────────────────────────────────────────────────────────────

export async function askQuestion(req: AskRequest): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method:  "POST",
    headers: authHeaders(),
    body:    JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json();
}

export async function streamQuestion(
  req: AskRequest,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/ask/stream", {
    method:  "POST",
    headers: authHeaders(),
    body:    JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }

  const reader  = res.body!.getReader();
  const decoder = new TextDecoder();
  let   buffer  = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6));
        switch (event.type) {
          case "sources":   callbacks.onSources(event.sources);   break;
          case "chunk":     callbacks.onChunk(event.text);        break;
          case "citations": callbacks.onCitations(event.valid);   break;
          case "done":      callbacks.onDone();                   return;
          case "error":     callbacks.onError(event.detail);      return;
        }
      } catch {
        // malformed line — skip
      }
    }
  }
}

// ── Admin API ─────────────────────────────────────────────────────────────────

export async function adminListUsers(): Promise<AdminUser[]> {
  const res = await fetch("/admin/users", { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to list users (${res.status})`);
  return res.json();
}

export async function adminCreateUser(payload: {
  email: string;
  password: string;
  role: string;
  allowed_tickers: string;
}): Promise<AdminUser> {
  const res = await fetch("/auth/register", {
    method:  "POST",
    headers: authHeaders(),
    body:    JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Failed to create user (${res.status})`);
  }
  return res.json();
}

export async function adminUpdateUser(
  userId: number,
  patch: { role?: string; allowed_tickers?: string; is_active?: boolean },
): Promise<void> {
  const res = await fetch(`/admin/users/${userId}`, {
    method:  "PATCH",
    headers: authHeaders(),
    body:    JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update user (${res.status})`);
}

export async function adminDeleteUser(userId: number): Promise<void> {
  const res = await fetch(`/admin/users/${userId}`, {
    method:  "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to delete user (${res.status})`);
}
