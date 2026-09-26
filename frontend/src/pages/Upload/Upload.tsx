import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import NavBar from "../../components/NavBar";
import ClassificationBadge from "../../components/ClassificationBadge";
import {
  ApiError,
  Category,
  DocumentOut,
  SUPPORTED_UPLOAD_EXTENSIONS,
  getTaxonomy,
  listDocuments,
  reclassifyDocument,
  uploadFile,
  uploadText,
} from "../../api/client";

type Mode = "text" | "file";

const ACCEPT_ATTR = SUPPORTED_UPLOAD_EXTENSIONS.join(",");

export default function Upload() {
  const [mode, setMode] = useState<Mode>("text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [labelFilter, setLabelFilter] = useState("");
  const [reclassifying, setReclassifying] = useState<string | null>(null);

  async function refresh(label = labelFilter) {
    try {
      setDocuments(await listDocuments(label || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load documents");
    }
  }

  useEffect(() => {
    refresh();
    // The label set is served by the backend so this picker cannot drift out
    // of sync with the taxonomy the classifier actually uses.
    getTaxonomy()
      .then((taxonomy) => setCategories(taxonomy.categories))
      .catch(() => setCategories([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setStatus(null);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setError(null);
    setStatus(null);
  }

  async function handleFilterChange(next: string) {
    setLabelFilter(next);
    await refresh(next);
  }

  async function handleReclassify(documentId: string) {
    setError(null);
    setReclassifying(documentId);
    try {
      const updated = await reclassifyDocument(documentId);
      setStatus(
        updated.classification_label
          ? `Re-classified "${updated.title}" as ${updated.classification_label}.`
          : `"${updated.title}" could not be classified confidently and is queued for review.`
      );
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Reclassification failed");
    } finally {
      setReclassifying(null);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus(null);
    setLoading(true);
    try {
      // `title` is optional for file uploads - the backend falls back to the
      // filename - but required when pasting raw text.
      const doc =
        mode === "file" && file
          ? await uploadFile(file, title.trim() || undefined)
          : await uploadText(title, text);
      const classified = doc.classification_label
        ? ` Classified as ${doc.classification_label}.`
        : doc.classification_status === "pending_review"
        ? " Could not be classified confidently - queued for human review."
        : "";
      setStatus(
        `Ingested "${doc.title}" -> ${doc.chunk_count} chunk(s) embedded and indexed.${classified}`
      );
      setTitle("");
      setText("");
      setFile(null);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ingestion failed");
    } finally {
      setLoading(false);
    }
  }

  const tabClass = (active: boolean) =>
    `px-3 py-1.5 text-sm rounded-md ${
      active ? "bg-synapse-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
    }`;

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Document Ingestion</h1>
        <p className="text-sm text-gray-500 mb-6">
          Paste plain text or upload a {SUPPORTED_UPLOAD_EXTENSIONS.join(" / ")} file. Documents are
          parsed, classified into the document taxonomy, chunked, embedded via the active LLM
          provider, and indexed in the vector store. Scanned/image-only PDFs have no text layer and
          need OCR, which is not implemented yet.
        </p>

        <div className="flex gap-2 mb-4">
          <button type="button" onClick={() => switchMode("text")} className={tabClass(mode === "text")}>
            Paste text
          </button>
          <button type="button" onClick={() => switchMode("file")} className={tabClass(mode === "file")}>
            Upload file
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 bg-white p-6 rounded-lg shadow">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Title {mode === "file" && <span className="text-gray-400">(optional)</span>}
            </label>
            <input
              required={mode === "text"}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={mode === "file" ? "Defaults to the filename" : ""}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          {mode === "text" ? (
            <div>
              <label className="block text-sm font-medium text-gray-700">Document text</label>
              <textarea
                required
                rows={10}
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono"
              />
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium text-gray-700">File</label>
              <input
                required
                type="file"
                accept={ACCEPT_ATTR}
                onChange={handleFileChange}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-gray-100 file:px-3 file:py-1.5 file:text-sm"
              />
              {file && (
                <p className="mt-2 text-xs text-gray-500">
                  {file.name} &middot; {(file.size / 1024).toFixed(1)} KB
                </p>
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}
          {status && <p className="text-sm text-green-700">{status}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-synapse-600 px-4 py-2 text-sm font-semibold text-white hover:bg-synapse-700 disabled:opacity-60"
          >
            {loading ? "Ingesting..." : "Ingest document"}
          </button>
        </form>

        <div className="flex items-center justify-between mt-8 mb-3">
          <h2 className="text-md font-semibold text-gray-900">Ingested documents</h2>
          <label className="text-sm text-gray-600">
            Category:{" "}
            <select
              value={labelFilter}
              onChange={(e) => handleFilterChange(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-sm"
            >
              <option value="">All</option>
              {categories.map((c) => (
                <option key={c.label} value={c.label} title={c.description}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="bg-white rounded-lg shadow divide-y">
          {documents.length === 0 && (
            <p className="p-4 text-sm text-gray-500">
              {labelFilter ? `No documents classified as ${labelFilter}.` : "No documents ingested yet."}
            </p>
          )}
          {documents.map((doc) => (
            <div key={doc.id} className="p-4 flex justify-between items-start gap-4 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-gray-900">{doc.title}</p>
                <p className="text-gray-500">
                  {doc.source_type} &middot; {doc.char_count} chars &middot; {doc.chunk_count} chunk(s)
                </p>
                <div className="mt-1.5">
                  <ClassificationBadge
                    label={doc.classification_label}
                    status={doc.classification_status}
                    confidence={doc.classification_confidence}
                  />
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <span className="text-gray-400">{new Date(doc.created_at).toLocaleString()}</span>
                <button
                  type="button"
                  onClick={() => handleReclassify(doc.id)}
                  disabled={reclassifying === doc.id}
                  className="text-xs text-synapse-600 hover:text-synapse-700 disabled:opacity-60"
                >
                  {reclassifying === doc.id ? "Re-classifying..." : "Re-classify"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
