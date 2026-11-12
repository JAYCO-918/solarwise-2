import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlantsPage } from "./pages/PlantsPage";
import { RegisterPage } from "./pages/RegisterPage";

const AnalysisPage = lazy(() => import("./pages/AnalysisPage"));
const DatasetPage = lazy(() => import("./pages/DatasetPage"));
const PlantFormPage = lazy(() => import("./pages/PlantFormPage"));
const PlantPage = lazy(() => import("./pages/PlantPage"));
const ReferencePage = lazy(() => import("./pages/ReferencePage"));
const UploadPage = lazy(() => import("./pages/UploadPage"));
const UsersPage = lazy(() => import("./pages/UsersPage"));

function Protected({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Loading label="Opening the session" />;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

export function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<Protected><Layout /></Protected>}>
          <Route index element={<Navigate to="/plants" replace />} />
          <Route path="/plants" element={<PlantsPage />} />
          <Route path="/plants/new" element={<PlantFormPage />} />
          <Route path="/plants/:plantId" element={<PlantPage />} />
          <Route path="/plants/:plantId/upload" element={<UploadPage />} />
          <Route path="/datasets/:datasetId" element={<DatasetPage />} />
          <Route path="/analyses/:analysisId" element={<AnalysisPage />} />
          <Route path="/reference" element={<ReferencePage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
