import { useEffect, useState } from "react";
import NavBar from "../../components/NavBar";
import ConfidenceBadge from "../../components/ConfidenceBadge";
import { ApiError, ReviewItem, listReviewQueue, submitReviewDecision } from "../../api/client";

export default function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rationale, setRationale] = useState<Record<string, string>>({});
  const [editedAnswer, setEditedAnswer] = useState<Record<string, string>>({});

  async function refresh() {
    try {
      setItems(await listReviewQueue("pending"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load review queue");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function decide(item: ReviewItem, decision: "approved" | "edited" | "rejected") {
    setError(null);
    const itemRationale = rationale[item.id] || "";
    if (!itemRationale.trim()) {
      setError("Rationale is required for every review decision.");
      return;
    }
    try {
      await submitReviewDecision(item.id, decision, itemRationale, editedAnswer[item.id]);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit decision");
    }
  }

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Human Review Queue</h1>
        <p className="text-sm text-gray-500 mb-6">
          Answers below the confidence threshold are routed here for a Reviewer or Admin to
          approve, edit, or reject. Every decision is captured to the feedback table for future
          eval-dataset building (see backend/app/scaffold/promptfoo/).
        </p>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {items.length === 0 && (
          <p className="text-sm text-gray-500 bg-white rounded-lg shadow p-4">
            Queue is empty - nothing pending review.
          </p>
        )}

        <div className="space-y-4">
          {items.map((item) => (
            <div key={item.id} className="bg-white rounded-lg shadow p-4">
              <p className="font-medium text-gray-900 mb-1">Q: {item.question}</p>
              <p className="text-sm text-gray-800 whitespace-pre-wrap mb-2">{item.proposed_answer}</p>
              <ConfidenceBadge confidence={item.confidence} />

              <div className="mt-3 space-y-2">
                <textarea
                  placeholder="Rationale (required)"
                  value={rationale[item.id] || ""}
                  onChange={(e) => setRationale((prev) => ({ ...prev, [item.id]: e.target.value }))}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  rows={2}
                />
                <textarea
                  placeholder="Edited answer (only used for 'edited' decision)"
                  value={editedAnswer[item.id] || ""}
                  onChange={(e) => setEditedAnswer((prev) => ({ ...prev, [item.id]: e.target.value }))}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  rows={2}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => decide(item, "approved")}
                    className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => decide(item, "edited")}
                    className="rounded-md bg-synapse-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-synapse-700"
                  >
                    Save edit
                  </button>
                  <button
                    onClick={() => decide(item, "rejected")}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
