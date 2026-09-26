import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, login } from "../../api/client";
import { setAuth } from "../../store/auth";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("T6-LEAD@synapse.example");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await login(email, password);
      setAuth({
        token: result.access_token,
        role: result.role,
        roleId: result.role_id,
      });
      navigate("/upload");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm bg-white shadow rounded-lg p-8">
        <h1 className="text-xl font-semibold text-synapse-900 mb-1">Project Synapse</h1>
        <p className="text-sm text-gray-500 mb-6">Sign in with your seeded role account.</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-synapse-500 focus:outline-none focus:ring-1 focus:ring-synapse-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-synapse-500 focus:outline-none focus:ring-1 focus:ring-synapse-500"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-synapse-600 px-3 py-2 text-sm font-semibold text-white hover:bg-synapse-700 disabled:opacity-60"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-xs text-gray-400">
          Local dev seed accounts (see docs/TEAM.md): T6-LEAD, T6-BE1, T6-DEV1,
          T6-DATA1/2/3 — default password <code>ChangeMe123!</code>.
        </p>
      </div>
    </div>
  );
}
