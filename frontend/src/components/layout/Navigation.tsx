import React from "react";
import {
  FolderTree,
  History,
  LayoutDashboard,
  Play,
  ShieldCheck,
} from "lucide-react";

export type NavTab =
  | "home"
  | "dashboard"
  | "workspaces"
  | "history"
  | "governance";

interface NavigationProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
}

const TABS = [
  { id: "home" as const, label: "Execution", icon: Play, primary: true },
  {
    id: "dashboard" as const,
    label: "Dashboard",
    icon: LayoutDashboard,
    primary: false,
  },
  {
    id: "workspaces" as const,
    label: "Workspaces",
    icon: FolderTree,
    primary: false,
  },
  { id: "history" as const, label: "History", icon: History, primary: false },
  {
    id: "governance" as const,
    label: "Governance",
    icon: ShieldCheck,
    primary: false,
  },
];

export const Navigation: React.FC<NavigationProps> = ({
  currentTab,
  onTabChange,
}) => {
  return (
    <nav
      aria-label="Console Navigation"
      className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-4 sm:px-6"
    >
      <div className="max-w-7xl mx-auto flex items-center overflow-x-auto py-2 scrollbar-none">
        <div className="flex items-center gap-1.5 sm:gap-2">
          {TABS.map(({ id, label, icon: Icon, primary }) => {
            const isActive = currentTab === id;
            return (
              <button
                key={id}
                onClick={() => onTabChange(id)}
                aria-current={isActive ? "page" : undefined}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono transition-all shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-600 select-none ${
                  isActive
                    ? primary
                      ? "bg-emerald-950/40 text-emerald-300 border border-emerald-600/50 font-semibold shadow-sm shadow-emerald-950/30"
                      : "bg-zinc-900 text-zinc-100 border border-zinc-700/90 font-semibold shadow-sm"
                    : primary
                      ? "text-zinc-300 hover:text-emerald-300 hover:bg-zinc-900/60 border border-zinc-800/60 hover:border-zinc-700"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/50 border border-transparent hover:border-zinc-800/60"
                }`}
              >
                <Icon
                  className={`w-3.5 h-3.5 shrink-0 transition-colors ${
                    primary
                      ? isActive
                        ? "text-emerald-400"
                        : "text-emerald-500/70"
                      : isActive
                        ? "text-cyan-400"
                        : "text-zinc-500"
                  }`}
                />
                <span>{label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
};
