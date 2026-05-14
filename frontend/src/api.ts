import type { AskRequest, AskResponse, StreamCallbacks } from "./types";

export async function askQuestion(req: AskRequest): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
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
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
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
    buffer = lines.pop() ?? "";     // keep incomplete last line

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
