export default function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  let colorClass = "bg-red-100 text-red-800";
  if (confidence >= 0.8) colorClass = "bg-green-100 text-green-800";
  else if (confidence >= 0.55) colorClass = "bg-yellow-100 text-yellow-800";

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      confidence: {pct}%
    </span>
  );
}
