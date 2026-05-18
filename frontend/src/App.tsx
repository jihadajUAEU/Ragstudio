import { lazy, Suspense, useEffect, useState } from "react";

import { AppShell } from "./components/app-shell";
import { ChunkInspector } from "./features/chunks/chunk-inspector";
import { ComparisonPage } from "./features/comparison/comparison-page";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { DiagnosticsPage } from "./features/diagnostics/diagnostics-page";
import { DocumentEvidencePage } from "./features/document-evidence/document-evidence-page";
import { DocumentsPage } from "./features/documents/documents-page";
import { EvaluationPage } from "./features/evaluation/evaluation-page";
import { ExperimentsPage } from "./features/experiments/experiments-page";
import { GraphPage } from "./features/graph/graph-page";
import { OptimizerPage } from "./features/optimizer/optimizer-page";
import { QueryPage } from "./features/query/query-page";
import { SettingsPage } from "./features/settings/settings-page";
import { VariantsPage } from "./features/variants/variants-page";

const PipelineBuilder = lazy(() =>
  import("./features/pipeline/pipeline-builder").then((module) => ({ default: module.PipelineBuilder })),
);

const pageTitles: Record<string, string> = {
  "/": "Studio Dashboard",
  "/pipeline": "Pipeline Builder",
  "/documents": "Documents",
  "/document-evidence": "Parse Evidence",
  "/chunks": "Chunk Inspector",
  "/query": "Query",
  "/evaluation": "Evaluation",
  "/experiments": "Experiments",
  "/comparison": "Comparison",
  "/optimizer": "Optimizer",
  "/variants": "Variants",
  "/graph": "Graph",
  "/diagnostics": "Diagnostics",
  "/settings": "Settings",
};

export default function App() {
  const readLocation = () => `${window.location.pathname}${window.location.search}`;
  const [activeLocation, setActiveLocation] = useState(readLocation);
  const pathname = new URL(activeLocation, window.location.origin).pathname;
  const route = pageTitles[pathname] ? pathname : "/";

  useEffect(() => {
    const handlePopState = () => setActiveLocation(readLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (path: string) => {
    if (path === window.location.pathname && window.location.search.length === 0) {
      return;
    }
    window.history.pushState(null, "", path);
    setActiveLocation(readLocation());
  };

  return (
    <AppShell activePath={route} title={pageTitles[route]} onNavigate={navigate}>
      <Suspense fallback={<div className="text-sm text-[#62717a]">Loading pipeline builder...</div>}>
        {route === "/pipeline" ? (
          <PipelineBuilder />
        ) : route === "/documents" ? (
          <DocumentsPage />
        ) : route === "/document-evidence" ? (
          <DocumentEvidencePage />
        ) : route === "/chunks" ? (
          <ChunkInspector />
        ) : route === "/query" ? (
          <QueryPage />
        ) : route === "/evaluation" ? (
          <EvaluationPage />
        ) : route === "/experiments" ? (
          <ExperimentsPage />
        ) : route === "/comparison" ? (
          <ComparisonPage />
        ) : route === "/optimizer" ? (
          <OptimizerPage />
        ) : route === "/variants" ? (
          <VariantsPage />
        ) : route === "/graph" ? (
          <GraphPage />
        ) : route === "/diagnostics" ? (
          <DiagnosticsPage />
        ) : route === "/settings" ? (
          <SettingsPage />
        ) : (
          <DashboardPage />
        )}
      </Suspense>
    </AppShell>
  );
}
