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
  onDone:      () => void;
  onError:     (detail: string) => void;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
}
