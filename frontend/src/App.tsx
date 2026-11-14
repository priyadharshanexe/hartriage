import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { AnalysisPage } from "./pages/AnalysisPage";
import { AuditPage } from "./pages/AuditPage";
import { InvitePage, LoginPage, RegisterPage } from "./pages/AuthPages";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { TeamPage } from "./pages/TeamPage";
import { UploadPage } from "./pages/UploadPage";
import { LoadingState } from "./components/ui";

// The Markdown renderer is only needed for KB articles: load it on first visit.
const KbIndexPage = lazy(() => import("./pages/KbPage").then((m) => ({ default: m.KbIndexPage })));
const KbPage = lazy(() => import("./pages/KbPage").then((m) => ({ default: m.KbPage })));

function RequireSession({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  return isAdmin ? <>{children}</> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/invite" element={<InvitePage />} />
      <Route
        element={
          <RequireSession>
            <Layout />
          </RequireSession>
        }
      >
        <Route index element={<UploadPage />} />
        <Route path="analyses" element={<HistoryPage />} />
        <Route path="analyses/:id" element={<AnalysisPage />} />
        <Route path="kb" element={<Suspense fallback={<LoadingState />}><KbIndexPage /></Suspense>} />
        <Route path="kb/:slug" element={<Suspense fallback={<LoadingState />}><KbPage /></Suspense>} />
        <Route path="connections" element={<AdminOnly><ConnectionsPage /></AdminOnly>} />
        <Route path="team" element={<AdminOnly><TeamPage /></AdminOnly>} />
        <Route path="audit" element={<AdminOnly><AuditPage /></AdminOnly>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
