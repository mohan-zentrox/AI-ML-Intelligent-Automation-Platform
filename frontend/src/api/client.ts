/**
 * Thin fetch wrapper for the Project Synapse backend API.
 *
 * All requests go through here so auth headers, base URL, and error
 * handling stay in one place. Auth token/API key are read from
 * src/store/auth.ts (localStorage-backed).
 */
import { getAuth } from "../store/auth";

/**
 * Normalise the configured base URL before it is ever concatenated with a path.
 *
 * VITE_API_BASE_URL is typed by hand into a hosting dashboard or a --build-arg,
 * so a stray trailing space or trailing slash is routine - and both fail
 * confusingly: the space produces ".../api/v1 /auth/login" and every request
 * 404s with no hint as to why, while a trailing slash produces a double slash.
 * Trimming here means the misconfiguration cannot reach a fetch call.
 */
function normaliseBaseUrl(raw: string | undefined): string {
  const fallback = "http://localhost:8000/api/v1";
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return fallback;
  return trimmed.replace(/\/+$/, "");
}

const API_BASE_URL: string = normaliseBaseUrl(import.meta.env.VITE_API_BASE_URL);

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

/** Provenance of a document's label - see backend ClassificationStatus. */
export type ClassificationStatus =
  | "unclassified"
  | "auto"
  | "pending_review"
  | "confirmed"
  | "corrected"
  | "rejected";

export interface DocumentOut {
  id: string;
  title: string;
  source_type: string;
  char_count: number;
  chunk_count: number;
  created_at: string;
  /** Null when unclassified, unclassifiable, or rejected by a reviewer. */
  classification_label: string | null;
  classification_confidence: number | null;
  classification_status: ClassificationStatus;
  taxonomy_version: string | null;
  classified_at: string | null;
}

export interface Category {
  label: string;
  description: string;
}

export interface Taxonomy {
  version: string;
  categories: Category[];
}

/**
 * The active document taxonomy. Fetched rather than hardcoded so label
 * pickers cannot drift out of sync with the backend's label set.
 */
export function getTaxonomy(): Promise<Taxonomy> {
  return request<Taxonomy>("/documents/taxonomy");
}

/** Re-run classification for one document (Admin / Workflow Builder only). */
export function reclassifyDocument(documentId: string): Promise<DocumentOut> {
  return request<DocumentOut>(`/documents/${documentId}/reclassify`, { method: "POST" });
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

export function listDocuments(label?: string): Promise<DocumentOut[]> {
  const qs = label ? `?label=${encodeURIComponent(label)}` : "";
  return request<DocumentOut[]>(`/documents${qs}`);
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

/**
 * "answer"         - low-confidence RAG answer; `proposed_answer` is the text.
 * "classification" - low-confidence document label; `proposed_answer` is the
 *                    proposed taxonomy label and `final_answer` on an edit
 *                    must be a label from the taxonomy.
 */
export type ReviewItemType = "answer" | "classification";

export interface ReviewItem {
  id: string;
  item_type: ReviewItemType;
  document_id: string | null;
  question: string;
  proposed_answer: string;
  citations: Citation[];
  confidence: number;
  status: string;
  final_answer: string | null;
  rationale: string | null;
  created_at: string;
}

export function listReviewQueue(
  status?: string,
  itemType?: ReviewItemType
): Promise<ReviewItem[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (itemType) params.set("item_type", itemType);
  const qs = params.toString();
  return request<ReviewItem[]>(`/review/queue${qs ? `?${qs}` : ""}`);
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
