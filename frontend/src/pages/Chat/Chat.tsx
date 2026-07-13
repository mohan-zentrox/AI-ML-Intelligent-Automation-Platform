import { FormEvent, useState } from "react";
import NavBar from "../../components/NavBar";
import ConfidenceBadge from "../../components/ConfidenceBadge";
import { ApiError, QueryResponse, askQuestion } from "../../api/client";

interface Turn {
  question: string;
  response: QueryResponse;
}

export default function Chat() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const response = await askQuestion(question);
      setTurns((prev) => [...prev, { question, response }]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Grounded Q&amp;A</h1>
        <p className="text-sm text-gray-500 mb-6">
          Answers are grounded only in ingested document chunks and always include citations.
          If nothing clears the similarity threshold, the platform refuses rather than
          guessing (see docs/RESPONSIBLE_AI.md).
        </p>

        <div className="space-y-4 mb-6">
          {turns.map((turn, i) => (
            <div key={i} className="bg-white rounded-lg shadow p-4">
              <p className="font-medium text-gray-900 mb-2">Q: {turn.question}</p>
              <p className="text-sm text-gray-800 whitespace-pre-wrap mb-3">{turn.response.answer}</p>
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <ConfidenceBadge confidence={turn.response.confidence} />
                {turn.response.refused && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-200 text-gray-700">
                    refused - insufficient context
                  </span>
                )}
                {turn.response.routed_to_review && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                    routed to human review
                  </span>
                )}
              </div>
              {turn.response.citations.length > 0 && (
                <div className="text-xs text-gray-500 space-y-1">
                  {turn.response.citations.map((c) => (
                    <div key={c.chunk_id}>
                      [{c.marker}] doc {c.document_id.slice(0, 8)} &middot; score {c.score.toFixed(3)} &middot;{" "}
                      &ldquo;{c.snippet}&rdquo;
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your ingested documents..."
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-synapse-600 px-4 py-2 text-sm font-semibold text-white hover:bg-synapse-700 disabled:opacity-60"
          >
            {loading ? "Asking..." : "Ask"}
          </button>
        </form>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>
    </div>
  );
}
