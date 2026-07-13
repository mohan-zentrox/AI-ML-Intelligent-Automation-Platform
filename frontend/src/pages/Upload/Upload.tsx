import { FormEvent, useEffect, useState } from "react";
import NavBar from "../../components/NavBar";
import { ApiError, DocumentOut, listDocuments, uploadText } from "../../api/client";

export default function Upload() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    try {
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load documents");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus(null);
    setLoading(true);
    try {
      const doc = await uploadText(title, text);
      setStatus(`Ingested "${doc.title}" -> ${doc.chunk_count} chunk(s) embedded and indexed.`);
      setTitle("");
      setText("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ingestion failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Document Ingestion</h1>
        <p className="text-sm text-gray-500 mb-6">
          Paste plain text (PDF/DOCX/OCR upload is scaffolded - see backend/app/scaffold/parsers.py).
          Documents are chunked, embedded via the active LLM provider, and indexed in the vector store.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4 bg-white p-6 rounded-lg shadow">
          <div>
            <label className="block text-sm font-medium text-gray-700">Title</label>
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
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

        <h2 className="text-md font-semibold text-gray-900 mt-8 mb-3">Ingested documents</h2>
        <div className="bg-white rounded-lg shadow divide-y">
          {documents.length === 0 && (
            <p className="p-4 text-sm text-gray-500">No documents ingested yet.</p>
          )}
          {documents.map((doc) => (
            <div key={doc.id} className="p-4 flex justify-between items-center text-sm">
              <div>
                <p className="font-medium text-gray-900">{doc.title}</p>
                <p className="text-gray-500">
                  {doc.source_type} &middot; {doc.char_count} chars &middot; {doc.chunk_count} chunk(s)
                </p>
              </div>
              <span className="text-gray-400">{new Date(doc.created_at).toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
