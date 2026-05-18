import {
  BarChart3,
  Database,
  Gauge,
  FileText,
  FlaskConical,
  GitBranch,
  GitCompare,
  GitFork,
  ShieldCheck,
  LayoutDashboard,
  MessageSquareText,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface StudioRoute {
  href: string;
  label: string;
  icon: LucideIcon;
  enabled: boolean;
}

export const studioRoutes: StudioRoute[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, enabled: true },
  { href: "/pipeline", label: "Pipeline", icon: GitFork, enabled: true },
  { href: "/documents", label: "Documents", icon: FileText, enabled: true },
  { href: "/document-evidence", label: "Evidence", icon: ShieldCheck, enabled: true },
  { href: "/chunks", label: "Chunks", icon: Database, enabled: true },
  { href: "/query", label: "Query", icon: MessageSquareText, enabled: true },
  { href: "/evaluation", label: "Evaluation", icon: BarChart3, enabled: true },
  { href: "/experiments", label: "Experiments", icon: FlaskConical, enabled: true },
  { href: "/comparison", label: "Comparison", icon: GitCompare, enabled: true },
  { href: "/optimizer", label: "Optimizer", icon: SlidersHorizontal, enabled: true },
  { href: "/variants", label: "Variants", icon: SlidersHorizontal, enabled: true },
  { href: "/graph", label: "Graph", icon: GitBranch, enabled: true },
  { href: "/diagnostics", label: "Diagnostics", icon: Gauge, enabled: true },
  { href: "/settings", label: "Settings", icon: Settings, enabled: true },
];
