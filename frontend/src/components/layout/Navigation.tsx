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
    <nav className="border-b border-zinc-800/80 bg-zinc-950 px-6">
      <div className="max-w-7xl mx-auto flex items-center justify-between overflow-x-auto py-2">
        <div className="flex items-center gap-2">
          {TABS.map(({ id, label, icon: Icon, primary }) => {
            const isActive = currentTab === id;
            return (
              <button
                key={id}
                onClick={() => onTabChange(id)}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? primary
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 shadow-sm"
                      : "bg-zinc-800 text-zinc-100 border border-zinc-700 shadow-sm"
                    : primary
                      ? "text-zinc-200 hover:text-emerald-300 hover:bg-zinc-900 border border-zinc-800/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
                }`}
              >
                <Icon
                  className={`w-3.5 h-3.5 ${primary && isActive ? "text-emerald-400" : ""}`}
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
