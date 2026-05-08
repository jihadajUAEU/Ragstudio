import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { AppShell } from "./components/app-shell";
import { ChunkInspector } from "./features/chunks/chunk-inspector";
import { ComparisonPage } from "./features/comparison/comparison-page";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { DiagnosticsPage } from "./features/diagnostics/diagnostics-page";
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
  const [activePath, setActivePath] = useState(() => window.location.pathname);
  const route = pageTitles[activePath] ? activePath : "/";

  useEffect(() => {
    const handlePopState = () => setActivePath(window.location.pathname);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const page = useMemo(() => {
    switch (route) {
      case "/pipeline":
        return <PipelineBuilder />;
      case "/documents":
        return <DocumentsPage />;
      case "/chunks":
        return <ChunkInspector />;
      case "/query":
        return <QueryPage />;
      case "/evaluation":
        return <EvaluationPage />;
      case "/experiments":
        return <ExperimentsPage />;
      case "/comparison":
        return <ComparisonPage />;
      case "/optimizer":
        return <OptimizerPage />;
      case "/variants":
        return <VariantsPage />;
      case "/graph":
        return <GraphPage />;
      case "/diagnostics":
        return <DiagnosticsPage />;
      case "/settings":
        return <SettingsPage />;
      default:
        return <DashboardPage />;
    }
  }, [route]);

  const navigate = (path: string) => {
    if (path === activePath) {
      return;
    }
    window.history.pushState(null, "", path);
    setActivePath(path);
  };

  return (
    <AppShell activePath={route} title={pageTitles[route]} onNavigate={navigate}>
      <Suspense fallback={<div className="text-sm text-[#62717a]">Loading pipeline builder...</div>}>{page}</Suspense>
    </AppShell>
  );
}
