import { useEffect, useState } from "react";
import NavBar from "../../components/NavBar";
import ConfidenceBadge from "../../components/ConfidenceBadge";
import {
  ApiError,
  Category,
  ReviewItem,
  ReviewItemType,
  getTaxonomy,
  listReviewQueue,
  submitReviewDecision,
} from "../../api/client";

type Filter = "all" | ReviewItemType;

export default function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rationale, setRationale] = useState<Record<string, string>>({});
  const [editedAnswer, setEditedAnswer] = useState<Record<string, string>>({});
  const [categories, setCategories] = useState<Category[]>([]);
  const [filter, setFilter] = useState<Filter>("all");

  async function refresh(next: Filter = filter) {
    try {
      setItems(await listReviewQueue("pending", next === "all" ? undefined : next));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load review queue");
    }
  }

  useEffect(() => {
    refresh();
    getTaxonomy()
      .then((taxonomy) => setCategories(taxonomy.categories))
      .catch(() => setCategories([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function changeFilter(next: Filter) {
    setFilter(next);
    setError(null);
    await refresh(next);
  }

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

  const filterClass = (active: boolean) =>
    `px-3 py-1.5 text-sm rounded-md ${
      active ? "bg-synapse-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
    }`;

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Human Review Queue</h1>
        <p className="text-sm text-gray-500 mb-4">
          Answers and document classifications below their confidence thresholds are routed here for
          a Reviewer or Admin to approve, edit, or reject. A resolved classification is written back
          onto the document, so a confirmed or corrected label is what downstream routing then uses.
          Every decision is captured to the feedback table for future eval-dataset building (see
          backend/app/scaffold/promptfoo/).
        </p>

        <div className="flex gap-2 mb-4">
          {(["all", "answer", "classification"] as Filter[]).map((f) => (
            <button key={f} type="button" onClick={() => changeFilter(f)} className={filterClass(filter === f)}>
              {f === "all" ? "All" : f === "answer" ? "Answers" : "Classifications"}
            </button>
          ))}
        </div>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {items.length === 0 && (
          <p className="text-sm text-gray-500 bg-white rounded-lg shadow p-4">
            Queue is empty - nothing pending review.
          </p>
        )}

        <div className="space-y-4">
          {items.map((item) => {
            const isClassification = item.item_type === "classification";
            return (
              <div key={item.id} className="bg-white rounded-lg shadow p-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                    {isClassification ? "classification" : "answer"}
                  </span>
                  <ConfidenceBadge confidence={item.confidence} />
                </div>
                <p className="font-medium text-gray-900 mb-1">{item.question}</p>
                <p className="text-sm text-gray-800 whitespace-pre-wrap mb-2">
                  {isClassification ? (
                    <>
                      Proposed label: <span className="font-semibold">{item.proposed_answer}</span>
                    </>
                  ) : (
                    item.proposed_answer
                  )}
                </p>
                {isClassification && item.citations[0]?.snippet && (
                  <p className="text-xs text-gray-500 border-l-2 border-gray-200 pl-2 mb-2 whitespace-pre-wrap">
                    {String(item.citations[0].snippet)}
                  </p>
                )}

                <div className="mt-3 space-y-2">
                  <textarea
                    placeholder="Rationale (required)"
                    value={rationale[item.id] || ""}
                    onChange={(e) => setRationale((prev) => ({ ...prev, [item.id]: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    rows={2}
                  />
                  {isClassification ? (
                    // A corrected label must be a real taxonomy category - the
                    // backend rejects anything else - so this is a picker, not
                    // a free-text box.
                    <select
                      value={editedAnswer[item.id] || ""}
                      onChange={(e) =>
                        setEditedAnswer((prev) => ({ ...prev, [item.id]: e.target.value }))
                      }
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      <option value="">Corrected label (only used for &apos;edited&apos; decision)</option>
                      {categories.map((c) => (
                        <option key={c.label} value={c.label} title={c.description}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <textarea
                      placeholder="Edited answer (only used for 'edited' decision)"
                      value={editedAnswer[item.id] || ""}
                      onChange={(e) =>
                        setEditedAnswer((prev) => ({ ...prev, [item.id]: e.target.value }))
                      }
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      rows={2}
                    />
                  )}
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
                      {isClassification ? "Save label" : "Save edit"}
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
            );
          })}
        </div>
      </div>
    </div>
  );
}
