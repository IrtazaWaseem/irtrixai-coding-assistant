import React from "react";
import { Header } from "../Header";
import { Navigation, NavTab } from "./Navigation";
import { useTaskExecution } from "../../context/TaskContext";

interface AppLayoutProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  currentTab,
  onTabChange,
  children,
}) => {
  const { taskId, status, connectionState, handleReset } = useTaskExecution();

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-emerald-950 selection:text-emerald-300">
      <div className="sticky top-0 z-40 flex flex-col shadow-lg shadow-black/40">
        <Header
          taskId={taskId}
          status={status}
          connectionState={connectionState}
          onReset={handleReset}
        />
        <Navigation currentTab={currentTab} onTabChange={onTabChange} />
      </div>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-5 sm:py-6 focus:outline-none">
        {children}
      </main>
    </div>
  );
};
