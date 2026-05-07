import {
  BarChart3,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
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
  { href: "/documents", label: "Documents", icon: FileText, enabled: true },
  { href: "/chunks", label: "Chunks", icon: Database, enabled: false },
  { href: "/query", label: "Query", icon: MessageSquareText, enabled: false },
  { href: "/experiments", label: "Experiments", icon: FlaskConical, enabled: false },
  { href: "/variants", label: "Variants", icon: SlidersHorizontal, enabled: true },
  { href: "/graph", label: "Graph", icon: GitBranch, enabled: false },
  { href: "/runs", label: "Runs", icon: BarChart3, enabled: false },
  { href: "/settings", label: "Settings", icon: Settings, enabled: true },
];
