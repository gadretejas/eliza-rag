export interface Source {
  index: number;
  ticker: string;
  filing_type: string;
  filing_date: string;
  section: string;
  snippet: string;
}

export interface AskRequest {
  question: string;
  model: string;
  top_k: number;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
}
