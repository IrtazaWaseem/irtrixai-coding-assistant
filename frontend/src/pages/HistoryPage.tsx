import React from "react";
import { History } from "lucide-react";
import { useTaskExecution } from "../context/TaskContext";

export const HistoryPage: React.FC = () => {
  const { taskId, status, events } = useTaskExecution();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">Execution History</h1>
        <p className="text-xs text-zinc-400 mt-0.5">
          Auditable record of current and restored agent tasks.
        </p>
      </div>

      {taskId ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <span className="text-xs font-mono text-zinc-300 font-medium">
              Task: {taskId}
            </span>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-zinc-800 px-2 py-0.5 rounded text-zinc-400">
              {status}
            </span>
          </div>
          <div className="text-xs font-mono text-zinc-500">
            {events.length} lifecycle events recorded in session
          </div>
          <button
            onClick={() => {
              window.location.hash = "home";
            }}
            className="text-xs font-medium text-emerald-400 hover:text-emerald-300 pt-1"
          >
            Open in Execution Workspace →
          </button>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2">
          <History className="w-8 h-8 text-zinc-700 mx-auto" />
          <p className="text-xs font-medium text-zinc-400">
            No task active in this browser session
          </p>
          <p className="text-[11px] text-zinc-600">
            Tasks initiated from Execution or restored via URL parameter appear
            here.
          </p>
        </div>
      )}
    </div>
  );
};
