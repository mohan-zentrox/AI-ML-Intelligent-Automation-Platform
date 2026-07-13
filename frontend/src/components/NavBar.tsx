import { Link, useNavigate } from "react-router-dom";
import { clearAuth, getAuth } from "../store/auth";

export default function NavBar() {
  const navigate = useNavigate();
  const auth = getAuth();

  function handleLogout() {
    clearAuth();
    navigate("/login");
  }

  if (!auth) return null;

  const linkClass = "px-3 py-2 rounded-md text-sm font-medium text-white hover:bg-synapse-700";

  return (
    <nav className="bg-synapse-900 shadow">
      <div className="mx-auto max-w-6xl px-4 flex h-14 items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-white font-semibold mr-4">Project Synapse</span>
          <Link to="/upload" className={linkClass}>Upload</Link>
          <Link to="/chat" className={linkClass}>Chat</Link>
          <Link to="/review" className={linkClass}>Review Queue</Link>
          <Link to="/usage" className={linkClass}>Usage</Link>
        </div>
        <div className="flex items-center gap-3 text-synapse-100 text-sm">
          <span>{auth.roleId} &middot; {auth.role}</span>
          <button
            onClick={handleLogout}
            className="px-3 py-1.5 rounded-md bg-synapse-600 text-white hover:bg-synapse-500"
          >
            Log out
          </button>
        </div>
      </div>
    </nav>
  );
}
