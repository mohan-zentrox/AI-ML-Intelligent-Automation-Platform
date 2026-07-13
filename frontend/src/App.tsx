import { Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login/Login";
import Upload from "./pages/Upload/Upload";
import Chat from "./pages/Chat/Chat";
import ReviewQueue from "./pages/ReviewQueue/ReviewQueue";
import UsageDashboard from "./pages/UsageDashboard/UsageDashboard";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/upload"
        element={
          <ProtectedRoute>
            <Upload />
          </ProtectedRoute>
        }
      />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <Chat />
          </ProtectedRoute>
        }
      />
      <Route
        path="/review"
        element={
          <ProtectedRoute>
            <ReviewQueue />
          </ProtectedRoute>
        }
      />
      <Route
        path="/usage"
        element={
          <ProtectedRoute>
            <UsageDashboard />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
