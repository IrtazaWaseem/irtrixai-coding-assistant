import React, { useEffect, useState } from "react";
import { TaskProvider } from "./context/TaskContext";
import { AppLayout } from "./components/layout/AppLayout";
import { NavTab } from "./components/layout/Navigation";
import { HomePage } from "./pages/HomePage";
import { DashboardPage } from "./pages/DashboardPage";
import { WorkspacesPage } from "./pages/WorkspacesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { GovernancePage } from "./pages/GovernancePage";

const VALID_TABS: NavTab[] = [
  "home",
  "dashboard",
  "workspaces",
  "history",
  "governance",
];

const getTabFromHash = (): NavTab => {
  const hash = window.location.hash.replace("#", "").toLowerCase() as NavTab;
  return VALID_TABS.includes(hash) ? hash : "home";
};

export const AppContent: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavTab>(getTabFromHash);

  useEffect(() => {
    const handleHashChange = () => {
      setCurrentTab(getTabFromHash());
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => {
      window.removeEventListener("hashchange", handleHashChange);
    };
  }, []);

  const handleTabChange = (tab: NavTab) => {
    window.location.hash = tab;
    setCurrentTab(tab);
  };

  const renderCurrentPage = () => {
    switch (currentTab) {
      case "dashboard":
        return <DashboardPage />;
      case "workspaces":
        return <WorkspacesPage />;
      case "history":
        return <HistoryPage />;
      case "governance":
        return <GovernancePage />;
      case "home":
      default:
        return <HomePage />;
    }
  };

  return (
    <AppLayout currentTab={currentTab} onTabChange={handleTabChange}>
      {renderCurrentPage()}
    </AppLayout>
  );
};

export const App: React.FC = () => {
  return (
    <TaskProvider>
      <AppContent />
    </TaskProvider>
  );
};

export default App;
