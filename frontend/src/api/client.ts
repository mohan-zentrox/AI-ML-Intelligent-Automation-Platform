/**
 * Thin fetch wrapper for the Project Synapse backend API.
 *
 * All requests go through here so auth headers, base URL, and error
 * handling stay in one place. Auth token/API key are read from
 * src/store/auth.ts (localStorage-backed).
 */
import { getAuth } from "../store/auth";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Auth headers only - deliberately no Content-Type, so multipart uploads can
 * reuse this and let the browser set the multipart boundary itself.
 */
function authHeaders(): Record<string, string> {
  const auth = getAuth();
  if (auth?.apiKey) {
    return { "X-API-Key": auth.apiKey };
  }
  if (auth?.token) {
    return { Authorization: `Bearer ${auth.token}` };
  }
  return {};
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: string = response.statusText;
  try {
    const body = await response.json();
    detail = body.detail ?? detail;
  } catch {
    // response had no JSON body
  }
  return new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail));
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// --- Auth ---
export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  role_id: string;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// --- Documents ---
export interface DocumentOut {
  id: string;
  title: string;
  source_type: string;
  char_count: number;
  chunk_count: number;
  created_at: string;
}

export function uploadText(title: string, text: string): Promise<DocumentOut> {
  return request<DocumentOut>("/documents/text", {
    method: "POST",
    body: JSON.stringify({ title, text }),
  });
}

/** Extensions the backend registers in app/services/parsers.PARSERS. */
export const SUPPORTED_UPLOAD_EXTENSIONS = [".txt", ".md", ".pdf", ".docx"] as const;

/**
 * Multipart upload for .txt/.md/.pdf/.docx. Bypasses `request` because the
 * browser must set the multipart Content-Type (with its boundary) itself;
 * setting it manually produces a malformed body FastAPI cannot parse.
 */
export async function uploadFile(file: File, title?: string): Promise<DocumentOut> {
  const form = new FormData();
  form.append("file", file);
  if (title) {
    form.append("title", title);
  }

  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as DocumentOut;
}

export function listDocuments(): Promise<DocumentOut[]> {
  return request<DocumentOut[]>("/documents");
}

// --- Query ---
export interface Citation {
  marker: number;
  document_id: string;
  chunk_id: string;
  score: number;
  snippet: string;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  confidence: number;
  refused: boolean;
  query_log_id: string;
  routed_to_review: boolean;
}

export function askQuestion(question: string): Promise<QueryResponse> {
  return request<QueryResponse>("/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

// --- Review queue ---
export interface ReviewItem {
  id: string;
  question: string;
  proposed_answer: string;
  citations: Citation[];
  confidence: number;
  status: string;
  final_answer: string | null;
  rationale: string | null;
  created_at: string;
}

export function listReviewQueue(status?: string): Promise<ReviewItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<ReviewItem[]>(`/review/queue${qs}`);
}

export function submitReviewDecision(
  reviewItemId: string,
  decision: "approved" | "edited" | "rejected",
  rationale: string,
  finalAnswer?: string
): Promise<ReviewItem> {
  return request<ReviewItem>(`/review/queue/${reviewItemId}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, rationale, final_answer: finalAnswer }),
  });
}

// --- Analytics ---
export interface UsageByDay {
  day: string;
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
}

export interface UsageByUser {
  user_id: string;
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
}

export interface UsageSummary {
  by_day: UsageByDay[];
  by_user: UsageByUser[];
  total_cost_usd: number;
  total_tokens: number;
}

export function getUsageSummary(): Promise<UsageSummary> {
  return request<UsageSummary>("/analytics/usage");
}
