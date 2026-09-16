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
  { id: "home" as const, label: "Execution", icon: Play },
  { id: "dashboard" as const, label: "Dashboard", icon: LayoutDashboard },
  { id: "workspaces" as const, label: "Workspaces", icon: FolderTree },
  { id: "history" as const, label: "History", icon: History },
  { id: "governance" as const, label: "Governance", icon: ShieldCheck },
];

export const Navigation: React.FC<NavigationProps> = ({
  currentTab,
  onTabChange,
}) => {
  return (
    <nav className="border-b border-zinc-800 bg-zinc-950/60 backdrop-blur-md px-6">
      <div className="max-w-7xl mx-auto flex items-center gap-2 overflow-x-auto py-2">
        {TABS.map(({ id, label, icon: Icon }) => {
          const isActive = currentTab === id;
          return (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                isActive
                  ? "bg-zinc-800 text-zinc-100 border border-zinc-700 shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
