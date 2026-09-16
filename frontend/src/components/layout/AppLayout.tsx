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
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans">
      <Header
        taskId={taskId}
        status={status}
        connectionState={connectionState}
        onReset={handleReset}
      />
      <Navigation currentTab={currentTab} onTabChange={onTabChange} />
      <main className="flex-1 max-w-7xl w-full mx-auto p-6">{children}</main>
    </div>
  );
};
