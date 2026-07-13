import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { isAuthenticated } from "../store/auth";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
