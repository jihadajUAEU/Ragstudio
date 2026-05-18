import { Activity, Menu, X } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { rs } from "../lib/design-tokens";
import { studioRoutes } from "../lib/routes";
import { cn } from "../lib/utils";
import { FocusTrapDialog } from "./focus-trap-dialog";
import { RuntimeTrust } from "./runtime-trust";
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

  return (
    <div className={cn("min-h-screen", rs.bg.page, rs.text.body)}>
      <FocusTrapDialog
        open={isMobileNavOpen}
        ariaLabel="Studio navigation"
        overlayLabel="Close navigation"
        panelId="studio-mobile-navigation"
        onClose={() => setIsMobileNavOpen(false)}
        overlayClassName="lg:hidden"
        className={cn("fixed inset-y-0 left-0 z-30 w-64 border-r lg:hidden", rs.border.line, rs.bg.paper)}
      >
        <aside>
          <SidebarContent
            activePath={activePath}
            onClose={() => setIsMobileNavOpen(false)}
            onNavigate={(path) => {
              onNavigate(path);
              setIsMobileNavOpen(false);
            }}
          />
        </aside>
      </FocusTrapDialog>

      <aside className={cn("fixed inset-y-0 left-0 z-20 hidden w-64 border-r lg:block", rs.border.line, rs.bg.paper)}>
        <SidebarContent activePath={activePath} onNavigate={onNavigate} />
      </aside>

      <div className="lg:pl-64">
        <header className={cn("sticky top-0 z-10 border-b bg-[color-mix(in_srgb,var(--rs-paper)_95%,transparent)] backdrop-blur", rs.border.line)}>
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold lg:hidden">RAG-Anything Studio</p>
              <h1 className={cn("truncate text-lg font-semibold sm:text-xl", rs.text.ink)}>
                {title}
              </h1>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <RuntimeTrust onNavigate={onNavigate} />
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
      <div className={cn("flex h-16 items-center justify-between gap-3 border-b px-5", rs.border.line)}>
        <div className="flex min-w-0 items-center gap-3">
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-md", rs.bg.accent, rs.text.white)}>
            <Activity className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">RAG-Anything</p>
            <p className={cn("truncate text-xs", rs.text.muted)}>Studio Workbench</p>
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
              ? cn(rs.bg.accentSoft, rs.text.accentDeep)
              : route.enabled
                ? cn(rs.text.body, rs.hover.field)
                : rs.text.muted,
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
