import { ClassificationStatus } from "../api/client";

/**
 * A document's category plus who stands behind it (FRD 7).
 *
 * The status is shown rather than just the label because "the model guessed
 * this" and "a reviewer confirmed this" are very different claims, and the
 * platform's grounding policy says the difference must be visible - see
 * docs/RESPONSIBLE_AI.md.
 */
const STATUS_STYLES: Record<ClassificationStatus, { label: string; className: string }> = {
  unclassified: { label: "unclassified", className: "bg-gray-100 text-gray-600" },
  auto: { label: "auto", className: "bg-blue-100 text-blue-800" },
  pending_review: { label: "pending review", className: "bg-yellow-100 text-yellow-800" },
  confirmed: { label: "confirmed", className: "bg-green-100 text-green-800" },
  corrected: { label: "corrected", className: "bg-green-100 text-green-800" },
  rejected: { label: "rejected", className: "bg-red-100 text-red-800" },
};

export default function ClassificationBadge({
  label,
  status,
  confidence,
}: {
  label: string | null;
  status: ClassificationStatus;
  confidence?: number | null;
}) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.unclassified;
  const pct = confidence == null ? null : Math.round(confidence * 100);

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${style.className}`}
      title={`Classification status: ${style.label}`}
    >
      <span className="font-semibold">{label ?? "unlabelled"}</span>
      <span className="opacity-75">
        ({style.label}
        {pct === null ? "" : `, ${pct}%`})
      </span>
    </span>
  );
}
