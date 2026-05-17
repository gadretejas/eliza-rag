export interface Source {
  index: number;
  ticker: string;
  filing_type: string;
  filing_date: string;
  section: string;
  snippet: string;
}

export type Provider = "openai" | "anthropic" | "local";

export interface SavedModel {
  id: string;
  provider: Provider;
  apiKey: string;
  modelName: string;
  baseUrl: string;
}

export interface AskRequest {
  question: string;
  model: string;
  top_k: number;
  provider?: Provider;
  api_key?: string;
  base_url?: string;
}

export interface StreamCallbacks {
  onSources:   (sources: Source[]) => void;
  onChunk:     (text: string) => void;
  onCitations: (valid: number[]) => void;
  onSaved?:    (convId: number) => void;
  onDone:      () => void;
  onError:     (detail: string) => void;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export type Role = "admin" | "analyst" | "viewer";

export interface AuthUser {
  id:              number;
  email:           string;
  role:            Role;
  allowed_tickers: string;   // "*" or JSON array string
}

export interface LoginResponse {
  access_token: string;
  token_type:   string;
  role:         Role;
  email:        string;
}

export interface AdminUser {
  id:              number;
  email:           string;
  role:            Role;
  allowed_tickers: string;
  is_active:       boolean;
  created_at:      string;
}

// ── Follow-up Sessions ────────────────────────────────────────────────────────

export interface SessionMessage {
  id:         number;
  role:       "user" | "assistant";
  content:    string;
  sources:    Source[];
  tokens:     number;
  created_at: string;
}

export interface ChatSessionDetail {
  id:            number;
  title:         string;
  model:         string;
  created_at:    string;
  messages:      SessionMessage[];
  tokens_used:   number;
  context_limit: number;
}

// ── Admin Dashboard ───────────────────────────────────────────────────────────

export interface UserUsage {
  user_id:    number;
  email:      string;
  total:      number;
  by_model:   Record<string, number>;
  call_count: number;
}

export interface UsageStats {
  users:       UserUsage[];
  models:      string[];
  grand_total: number;
  total_calls: number;
}

// ── Chat History ──────────────────────────────────────────────────────────────

export interface ConversationSummary {
  id:         number;
  title:      string;
  model:      string;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  question: string;
  answer:   string;
  sources:  Source[];
}

export interface HistoryListResponse {
  items: ConversationSummary[];
  total: number;
}
