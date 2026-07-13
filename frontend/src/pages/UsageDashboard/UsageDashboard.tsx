import { useEffect, useState } from "react";
import NavBar from "../../components/NavBar";
import { ApiError, UsageSummary, getUsageSummary } from "../../api/client";

export default function UsageDashboard() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUsageSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load usage data"));
  }, []);

  return (
    <div>
      <NavBar />
      <div className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Usage &amp; Cost Analytics</h1>
        <p className="text-sm text-gray-500 mb-6">
          Every embedding/completion call is logged with tokens, cost, and latency
          (see backend/app/models/usage_log.py). The mock provider always reports $0 cost.
        </p>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {summary && (
          <>
            <div className="grid grid-cols-2 gap-4 mb-8">
              <div className="bg-white rounded-lg shadow p-4">
                <p className="text-xs text-gray-500 uppercase">Total tokens</p>
                <p className="text-2xl font-semibold text-gray-900">{summary.total_tokens.toLocaleString()}</p>
              </div>
              <div className="bg-white rounded-lg shadow p-4">
                <p className="text-xs text-gray-500 uppercase">Total cost (USD)</p>
                <p className="text-2xl font-semibold text-gray-900">${summary.total_cost_usd.toFixed(4)}</p>
              </div>
            </div>

            <h2 className="text-md font-semibold text-gray-900 mb-2">By day</h2>
            <table className="w-full text-sm bg-white rounded-lg shadow mb-8 overflow-hidden">
              <thead className="bg-gray-100 text-left text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Day</th>
                  <th className="px-3 py-2">Calls</th>
                  <th className="px-3 py-2">Tokens</th>
                  <th className="px-3 py-2">Cost (USD)</th>
                  <th className="px-3 py-2">Avg latency (ms)</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {summary.by_day.map((row) => (
                  <tr key={row.day}>
                    <td className="px-3 py-2">{row.day}</td>
                    <td className="px-3 py-2">{row.total_calls}</td>
                    <td className="px-3 py-2">{row.total_tokens}</td>
                    <td className="px-3 py-2">${row.total_cost_usd.toFixed(4)}</td>
                    <td className="px-3 py-2">{row.avg_latency_ms}</td>
                  </tr>
                ))}
                {summary.by_day.length === 0 && (
                  <tr>
                    <td className="px-3 py-4 text-gray-400" colSpan={5}>No usage recorded yet.</td>
                  </tr>
                )}
              </tbody>
            </table>

            <h2 className="text-md font-semibold text-gray-900 mb-2">By user</h2>
            <table className="w-full text-sm bg-white rounded-lg shadow overflow-hidden">
              <thead className="bg-gray-100 text-left text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">User ID</th>
                  <th className="px-3 py-2">Calls</th>
                  <th className="px-3 py-2">Tokens</th>
                  <th className="px-3 py-2">Cost (USD)</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {summary.by_user.map((row) => (
                  <tr key={row.user_id}>
                    <td className="px-3 py-2">{row.user_id}</td>
                    <td className="px-3 py-2">{row.total_calls}</td>
                    <td className="px-3 py-2">{row.total_tokens}</td>
                    <td className="px-3 py-2">${row.total_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
                {summary.by_user.length === 0 && (
                  <tr>
                    <td className="px-3 py-4 text-gray-400" colSpan={4}>No usage recorded yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
