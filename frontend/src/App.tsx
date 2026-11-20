import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { InvitePage, LoginPage, RegisterPage } from "./pages/AuthPages";
import { LoadingState } from "./components/ui";

// Each page is its own chunk, loaded on first visit (the KB's Markdown renderer too).
const UploadPage = lazy(() => import("./pages/UploadPage").then((m) => ({ default: m.UploadPage })));
const HistoryPage = lazy(() => import("./pages/HistoryPage").then((m) => ({ default: m.HistoryPage })));
const AnalysisPage = lazy(() => import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })));
const ConnectionsPage = lazy(() => import("./pages/ConnectionsPage").then((m) => ({ default: m.ConnectionsPage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })));
const AuditPage = lazy(() => import("./pages/AuditPage").then((m) => ({ default: m.AuditPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
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
        <Route index element={<Suspense fallback={<LoadingState />}><UploadPage /></Suspense>} />
        <Route path="analyses" element={<Suspense fallback={<LoadingState />}><HistoryPage /></Suspense>} />
        <Route path="analyses/:id" element={<Suspense fallback={<LoadingState />}><AnalysisPage /></Suspense>} />
        <Route path="kb" element={<Suspense fallback={<LoadingState />}><KbIndexPage /></Suspense>} />
        <Route path="kb/:slug" element={<Suspense fallback={<LoadingState />}><KbPage /></Suspense>} />
        <Route path="connections" element={<AdminOnly><Suspense fallback={<LoadingState />}><ConnectionsPage /></Suspense></AdminOnly>} />
        <Route path="team" element={<AdminOnly><Suspense fallback={<LoadingState />}><TeamPage /></Suspense></AdminOnly>} />
        <Route path="audit" element={<AdminOnly><Suspense fallback={<LoadingState />}><AuditPage /></Suspense></AdminOnly>} />
        <Route path="settings" element={<AdminOnly><Suspense fallback={<LoadingState />}><SettingsPage /></Suspense></AdminOnly>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
