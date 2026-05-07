import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { AppShell } from "./components/app-shell";
import { ChunkInspector } from "./features/chunks/chunk-inspector";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { DocumentsPage } from "./features/documents/documents-page";
import { GraphPage } from "./features/graph/graph-page";
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
  "/variants": "Variants",
  "/graph": "Graph",
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
      case "/variants":
        return <VariantsPage />;
      case "/graph":
        return <GraphPage />;
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
