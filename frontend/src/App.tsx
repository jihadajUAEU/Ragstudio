import { useEffect, useMemo, useState } from "react";

import { AppShell } from "./components/app-shell";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { DocumentsPage } from "./features/documents/documents-page";
import { SettingsPage } from "./features/settings/settings-page";
import { VariantsPage } from "./features/variants/variants-page";

const pageTitles: Record<string, string> = {
  "/": "Studio Dashboard",
  "/documents": "Documents",
  "/variants": "Variants",
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
      case "/documents":
        return <DocumentsPage />;
      case "/variants":
        return <VariantsPage />;
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
      {page}
    </AppShell>
  );
}
