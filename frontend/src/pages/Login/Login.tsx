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

        {/*
          Each credential sits on its own line and is the LAST thing on it.
          Nothing may follow a credential on the same line - not a full stop,
          not a comma. This block previously read "... password
          <code>ChangeMe123!</code>." and the sentence-ending period was flush
          against the code span, so selecting the password dragged the period
          in with it and login failed with "Invalid credentials" while the
          password looked correct on screen.

          The email is spelled out in full for the same reason: listing only
          "T6-LEAD" left people guessing at the domain, and @synapse.local -
          the obvious guess, and what the docs used to say - can never
          authenticate, because .local is an RFC 6762 special-use TLD that the
          email validator rejects outright.
        */}
        <div className="mt-6 space-y-1 text-xs text-gray-400">
          <p>Local dev seed accounts (see docs/TEAM.md)</p>
          <p>
            Email:{" "}
            <code className="select-all rounded bg-gray-100 px-1.5 py-0.5 font-mono text-gray-700">
              T6-LEAD@synapse.example
            </code>
          </p>
          <p>
            Password:{" "}
            <code className="select-all rounded bg-gray-100 px-1.5 py-0.5 font-mono text-gray-700">
              ChangeMe123!
            </code>
          </p>
          <p className="pt-1">
            Other roles replace T6-LEAD with T6-BE1, T6-DEV1, T6-DATA1, T6-DATA2 or T6-DATA3
          </p>
        </div>
      </div>
    </div>
  );
}
