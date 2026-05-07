import { Activity, PanelLeftClose } from "lucide-react";
import type { ReactNode } from "react";

import { studioRoutes } from "../lib/routes";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f5f7f8] text-[#24313a]">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-[#d6dde1] bg-[#fbfcfd] lg:block">
        <div className="flex h-16 items-center gap-3 border-b border-[#d6dde1] px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#176b87] text-white">
            <Activity className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">RAG-Anything</p>
            <p className="truncate text-xs text-[#6f7f87]">Studio Workbench</p>
          </div>
        </div>
        <nav className="space-y-1 px-3 py-4">
          {studioRoutes.map((route) => {
            const Icon = route.icon;
            return (
              <a
                key={route.href}
                href={route.href}
                aria-disabled={!route.enabled}
                className={cn(
                  "flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-medium",
                  route.enabled
                    ? "bg-[#e7f1f4] text-[#174657]"
                    : "cursor-not-allowed text-[#7e8b92]",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{route.label}</span>
              </a>
            );
          })}
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b border-[#d6dde1] bg-[#fbfcfd]/95 backdrop-blur">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold lg:hidden">RAG-Anything Studio</p>
              <h1 className="truncate text-lg font-semibold text-[#1f2933] sm:text-xl">
                Studio Dashboard
              </h1>
            </div>
            <Button variant="secondary" size="sm" className="shrink-0 lg:hidden" aria-label="Menu">
              <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </header>

        <main className="px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
