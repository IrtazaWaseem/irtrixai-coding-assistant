import React from "react";
import { Activity, ArrowRight, History } from "lucide-react";
import { useTaskExecution } from "../context/TaskContext";

export const HistoryPage: React.FC = () => {
  const { taskId, status, events } = useTaskExecution();

  const repairCount = events.filter((e) => e.type === "repair_started").length;
  const recentEvents = [...events].slice(-6).reverse();

  const getStatusBadge = () => {
    switch (status) {
      case "completed":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/60">
            Completed
          </span>
        );
      case "awaiting_approval":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-800/60">
            Awaiting Approval
          </span>
        );
      case "running":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-cyan-950/60 text-cyan-400 border border-cyan-800/60">
            Running
          </span>
        );
      case "failed":
      case "aborted":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-rose-950/60 text-rose-400 border border-rose-800/60">
            {status}
          </span>
        );
      default:
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-zinc-100">Execution History</h1>
        <p className="text-xs text-zinc-400 mt-0.5">
          Auditable session checkpoints and execution state transitions.
        </p>
      </div>

      {taskId ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-5 shadow-lg">
          {/* Header Bar */}
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div className="flex items-center gap-2.5">
              <History className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-mono text-zinc-300 font-medium">
                Active Session Task:{" "}
                <span className="text-zinc-100 font-semibold">{taskId}</span>
              </span>
            </div>
            {getStatusBadge()}
          </div>

          {/* Operational Metrics Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-mono">
            <div className="bg-zinc-950/60 p-3 rounded-lg border border-zinc-800/80 space-y-1">
              <span className="text-zinc-500 block text-[10px] uppercase">
                Checkpoint Events
              </span>
              <div className="text-sm font-semibold text-zinc-200">
                {events.length} recorded
              </div>
            </div>

            <div className="bg-zinc-950/60 p-3 rounded-lg border border-zinc-800/80 space-y-1">
              <span className="text-zinc-500 block text-[10px] uppercase">
                Repair Iterations
              </span>
              <div className="text-sm font-semibold text-amber-400">
                {repairCount} / 3 cycles
              </div>
            </div>

            <div className="bg-zinc-950/60 p-3 rounded-lg border border-zinc-800/80 space-y-1">
              <span className="text-zinc-500 block text-[10px] uppercase">
                Session Scope
              </span>
              <div className="text-sm font-semibold text-emerald-400">
                Active Browser State
              </div>
            </div>
          </div>

          {/* Recent Checkpoints Stream */}
          <div className="space-y-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-cyan-400" />
              <span>Recent Lifecycle Transitions</span>
            </h2>

            {recentEvents.length > 0 ? (
              <div className="space-y-1.5 font-mono text-xs">
                {recentEvents.map((evt, idx) => (
                  <div
                    key={evt.id || idx}
                    className="p-2.5 bg-zinc-950/50 rounded-lg border border-zinc-800/60 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0" />
                      <span className="text-zinc-200 truncate">
                        {evt.title || evt.type}
                      </span>
                    </div>
                    <span className="text-[10px] text-zinc-500 shrink-0 ml-3">
                      {evt.timestamp
                        ? new Date(evt.timestamp).toLocaleTimeString()
                        : "—"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-xs text-zinc-600 font-mono bg-zinc-950/30 rounded-lg border border-zinc-800/40">
                No checkpoint events recorded yet.
              </div>
            )}
          </div>

          {/* Action Link & Architecture Invariant Notice */}
          <div className="pt-2 border-t border-zinc-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <p className="text-[11px] font-mono text-zinc-500">
              Note: History displays checkpoints recorded in the current
              session.
            </p>
            <button
              onClick={() => {
                window.location.hash = "home";
              }}
              className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition-colors shrink-0"
            >
              <span>Open in Execution Studio</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center space-y-3 shadow-lg">
          <History className="w-8 h-8 text-zinc-700 mx-auto" />
          <div className="space-y-1">
            <p className="text-xs font-medium text-zinc-300">
              No task recorded in this browser session
            </p>
            <p className="text-[11px] text-zinc-500 max-w-sm mx-auto">
              Initiate a prompt in the Execution Studio to inspect live
              checkpoint history and verification metrics.
            </p>
          </div>
          <button
            onClick={() => {
              window.location.hash = "home";
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 border border-zinc-700 transition-colors"
          >
            <span>Go to Execution Studio</span>
            <ArrowRight className="w-3 h-3 text-emerald-400" />
          </button>
        </div>
      )}
    </div>
  );
};
