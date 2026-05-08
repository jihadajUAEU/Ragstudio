import { Activity, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { studioRoutes } from "../lib/routes";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";

export function AppShell({
  activePath,
  title,
  onNavigate,
  children,
}: {
  activePath: string;
  title: string;
  onNavigate: (path: string) => void;
  children: ReactNode;
}) {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!isMobileNavOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMobileNavOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isMobileNavOpen]);

  return (
    <div className="min-h-screen bg-[#f5f7f8] text-[#24313a]">
      {isMobileNavOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-20 bg-[#1f2933]/35 lg:hidden"
          aria-label="Close navigation"
          onClick={() => setIsMobileNavOpen(false)}
        />
      ) : null}

      {isMobileNavOpen ? (
        <aside
          id="studio-mobile-navigation"
          className="fixed inset-y-0 left-0 z-30 w-64 border-r border-[#d6dde1] bg-[#fbfcfd] lg:hidden"
        >
          <SidebarContent
            activePath={activePath}
            onClose={() => setIsMobileNavOpen(false)}
            onNavigate={(path) => {
              onNavigate(path);
              setIsMobileNavOpen(false);
            }}
          />
        </aside>
      ) : null}

      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-[#d6dde1] bg-[#fbfcfd] lg:block">
        <SidebarContent activePath={activePath} onNavigate={onNavigate} />
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b border-[#d6dde1] bg-[#fbfcfd]/95 backdrop-blur">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold lg:hidden">RAG-Anything Studio</p>
              <h1 className="truncate text-lg font-semibold text-[#1f2933] sm:text-xl">
                {title}
              </h1>
            </div>
            <Button
              variant="secondary"
              size="sm"
              className="shrink-0 lg:hidden"
              aria-label={isMobileNavOpen ? "Close navigation" : "Open navigation"}
              aria-controls="studio-mobile-navigation"
              aria-expanded={isMobileNavOpen}
              onClick={() => setIsMobileNavOpen((isOpen) => !isOpen)}
            >
              {isMobileNavOpen ? (
                <X className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Menu className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </div>
        </header>

        <main className="px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

function SidebarContent({
  activePath,
  onClose,
  onNavigate,
}: {
  activePath: string;
  onClose?: () => void;
  onNavigate?: (path: string) => void;
}) {
  return (
    <>
      <div className="flex h-16 items-center justify-between gap-3 border-b border-[#d6dde1] px-5">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#176b87] text-white">
            <Activity className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">RAG-Anything</p>
            <p className="truncate text-xs text-[#6f7f87]">Studio Workbench</p>
          </div>
        </div>
        {onClose ? (
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 lg:hidden"
            aria-label="Close navigation"
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        ) : null}
      </div>
      <nav className="space-y-1 px-3 py-4" aria-label="Studio">
        {studioRoutes.map((route) => {
          const Icon = route.icon;
          const className = cn(
            "flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-medium",
            route.enabled && route.href === activePath
              ? "bg-[#e7f1f4] text-[#174657]"
              : route.enabled
                ? "text-[#3a4a53] hover:bg-[#eef4f6]"
                : "text-[#7e8b92]",
          );

          if (!route.enabled) {
            return (
              <span key={route.href} className={className} aria-disabled="true">
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{route.label}</span>
              </span>
            );
          }

          return (
            <a
              key={route.href}
              href={route.href}
              className={className}
              aria-current={route.href === activePath ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onNavigate?.(route.href);
              }}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">{route.label}</span>
            </a>
          );
        })}
      </nav>
    </>
  );
}
