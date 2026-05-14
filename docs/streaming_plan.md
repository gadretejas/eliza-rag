# Streaming Answer Generation Plan

## Problem

The current `/api/ask` endpoint blocks until the entire LLM response is assembled before returning. For a typical answer this means 5–15 seconds of blank screen. Users have no feedback that anything is happening beyond a loading skeleton.

## Solution

Replace the blocking JSON response with **Server-Sent Events (SSE)**. The LLM tokens are forwarded to the browser as they arrive. Retrieved sources are sent as a separate early event so the user sees them while the answer is still generating.

**Cost impact:** None. API pricing is token-based, not delivery-based.

---

## Architecture

### Event stream format

Every event is a JSON object on a `data:` line:

```
data: {"type": "sources",   "sources": [...]}
data: {"type": "chunk",     "text": "Apple's primary risk..."}
data: {"type": "chunk",     "text": " factors include supply chain..."}
data: {"type": "citations", "valid": [1, 2, 3]}
data: {"type": "done"}
data: {"type": "error",     "detail": "LLM call failed: ..."}
```

Order is always: `sources` → one or more `chunk` → `citations` → `done`. An `error` event can appear at any point and terminates the stream.

### End-to-end flow

```
Browser                          FastAPI                         LLM API
  │                                 │                               │
  │── POST /api/ask/stream ────────►│                               │
  │                                 │── retrieve chunks ────────────┤ (chroma, ~300ms)
  │◄── data: {sources} ────────────│                               │
  │                                 │── open stream ───────────────►│
  │◄── data: {chunk: "Apple"} ─────│◄── token ─────────────────────│
  │◄── data: {chunk: "'s risk"} ───│◄── token ─────────────────────│
  │        ... tokens ...           │        ... tokens ...         │
  │◄── data: {citations} ──────────│◄── [stream closed] ───────────│
  │◄── data: {done} ───────────────│                               │
```

---

## Backend changes

### 1. `src/answer/answer.py` — add `LLMClient.stream()`

All three providers support streaming natively:

- **OpenAI / Local Ollama:** `client.chat.completions.create(..., stream=True)` yields `ChatCompletionChunk` objects; each has `.choices[0].delta.content`.
- **Anthropic:** `client.messages.stream(...)` context manager yields `RawContentBlockDeltaEvent`; each has `.delta.text`.

Add a `stream()` method alongside the existing `complete()`:

```python
def stream(self, system: str, user: str, temperature: float, max_tokens: int) -> Iterator[str]:
    """Yield raw token strings as they arrive from the provider."""
```

### 2. `src/answer/answer.py` — add `AnswerEngine.answer_stream()`

```python
def answer_stream(self, question: str) -> Iterator[dict]:
    """
    Yields SSE-ready dicts in order:
      {"type": "sources",   "sources": [...]}   ← before LLM call
      {"type": "chunk",     "text": "..."}       ← one per token
      {"type": "citations", "valid": [1, 2, 3]}  ← after stream ends
      {"type": "done"}
    Yields {"type": "error", "detail": "..."} on failure.
    """
```

Retrieval runs first (blocking, ~300ms). The sources event is emitted immediately so the browser can render the source panel before a single token arrives. Then the LLM stream is opened and each token is yielded. After the stream closes, citations are parsed from the accumulated text and sent as a final event.

### 3. `api/main.py` — new endpoint

```python
@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest):
    engine = _get_engine(req)

    def generate():
        for event in engine.answer_stream(req.question):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

`X-Accel-Buffering: no` disables nginx proxy buffering so tokens reach the browser immediately.

The existing `/api/ask` endpoint is left untouched for backward compatibility.

---

## Frontend changes

### 1. `frontend/src/api.ts` — add `streamQuestion()`

Uses `fetch` with a `ReadableStream` reader. Parses each `data: {...}` line and dispatches to typed callbacks:

```ts
interface StreamCallbacks {
  onSources:   (sources: Source[]) => void;
  onChunk:     (text: string) => void;
  onCitations: (valid: number[]) => void;
  onDone:      () => void;
  onError:     (detail: string) => void;
}

export async function streamQuestion(
  req: AskRequest,
  callbacks: StreamCallbacks,
): Promise<void>
```

### 2. `frontend/src/App.tsx` — progressive state

Replace the single `result: AskResponse | null` with:

```ts
const [streamingText, setStreamingText]       = useState("");
const [streamingSources, setStreamingSources] = useState<Source[]>([]);
const [validCitations, setValidCitations]     = useState<number[]>([]);
const [streaming, setStreaming]               = useState(false);
const [done, setDone]                         = useState(false);
```

`handleSubmit` calls `streamQuestion()` and wires the callbacks to these setters. The "active layout" condition becomes `streaming || done || error` instead of `result !== null`.

### 3. `frontend/src/components/AnswerPanel.tsx` — pending citations

While `streaming === true`, citation chips render in a **dimmed/pending** state (no click handler, reduced opacity). Once `done === true` and `validCitations` is populated, chips become interactive with the full highlight and scroll behaviour. No structural change to `renderWithCitations` needed — just pass a `pending` flag.

### 4. Source panel

`SourceList` renders as soon as the `sources` event arrives, before the answer starts streaming. No component changes needed — it already renders whenever `sources.length > 0`.

---

## Key decisions

| Topic | Decision | Reason |
|---|---|---|
| Protocol | SSE over WebSocket | One-directional; no upgrade handshake; works through most proxies |
| Sources timing | Sent before LLM call | User sees sources while answer is streaming — biggest UX win |
| Citation timing | Sent after streaming ends | Can only validate `[n]` markers against chunk list once full text is known |
| Error handling | `{"type":"error"}` event | HTTP 200 is already committed once streaming starts; status codes can't be used |
| Backward compat | Keep `/api/ask` | CLI (`answer.py`) and any other callers continue to work unchanged |
| Singleton cache | Unchanged | `LLMClient` instance is reused; streaming is just a different call on the same client |
| Anthropic delta | Normalised inside `stream()` | Provider differences hidden from `AnswerEngine` |

---

## File checklist

| File | Change |
|---|---|
| `src/answer/answer.py` | Add `LLMClient.stream()`, `AnswerEngine.answer_stream()` |
| `api/main.py` | Add `POST /api/ask/stream` endpoint |
| `frontend/src/api.ts` | Add `streamQuestion()` with SSE reader |
| `frontend/src/types.ts` | Add `StreamCallbacks` interface |
| `frontend/src/App.tsx` | Replace `result` with progressive state; wire `streamQuestion` |
| `frontend/src/components/AnswerPanel.tsx` | Add `pending` prop for in-flight citation chips |
