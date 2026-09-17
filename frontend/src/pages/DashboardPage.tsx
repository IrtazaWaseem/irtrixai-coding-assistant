import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Cpu,
  FolderTree,
  RotateCw,
  Server,
} from "lucide-react";
import { getLLMInfo, getSystemStatus, getWorkspaces } from "../services/api";
import {
  LLMInfoResponse,
  SystemStatusResponse,
  WorkspaceResponse,
} from "../types";
import { useTaskExecution } from "../context/TaskContext";

export const DashboardPage: React.FC = () => {
  const { taskId, status, events } = useTaskExecution();

  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(
    null,
  );
  const [llmInfo, setLlmInfo] = useState<LLMInfoResponse | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sys, llm, ws] = await Promise.all([
        getSystemStatus(),
        getLLMInfo(),
        getWorkspaces(),
      ]);
      setSystemStatus(sys);
      setLlmInfo(llm);
      setWorkspaces(ws);
    } catch (err: any) {
      setError(err.message || "Failed to load system telemetry.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const isHealthy =
    systemStatus?.status?.toLowerCase() === "active" ||
    systemStatus?.status?.toLowerCase() === "healthy" ||
    systemStatus?.status?.toLowerCase() === "ok";

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100">System Telemetry</h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Operational runtime parameters, LLM model gateway, and workspace
            status.
          </p>
        </div>
        <button
          onClick={fetchDashboardData}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 border border-zinc-800 transition-colors disabled:opacity-50"
        >
          <RotateCw
            className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`}
          />
          <span>Refresh</span>
        </button>
      </div>

      {error && (
        <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={fetchDashboardData}
            className="underline hover:text-rose-200 font-semibold"
          >
            Retry
          </button>
        </div>
      )}

      {/* Telemetry Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Section A: Backend */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-zinc-400 text-xs">
              <span className="font-semibold uppercase tracking-wider text-[10px]">
                Backend Server
              </span>
              <Server className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isHealthy ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"
                  }`}
                />
                <span className="font-medium text-zinc-100 text-sm capitalize">
                  {systemStatus
                    ? `${systemStatus.status} status`
                    : isLoading
                      ? "Querying..."
                      : "Offline"}
                </span>
              </div>
              <div className="text-xs font-mono text-zinc-500 mt-1">
                Version: {systemStatus?.version || "—"} · Env:{" "}
                {systemStatus?.environment || "—"}
              </div>
            </div>
          </div>
        </div>

        {/* Section B: Model */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-zinc-400 text-xs">
              <span className="font-semibold uppercase tracking-wider text-[10px]">
                Model Gateway
              </span>
              <Cpu className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <div className="font-medium text-zinc-100 text-sm truncate">
                {llmInfo?.display_name ||
                  llmInfo?.model ||
                  (isLoading ? "Resolving..." : "Unavailable")}
              </div>
              <div className="text-xs font-mono text-zinc-500 mt-1 capitalize">
                Provider: {llmInfo?.provider || "—"}{" "}
                {llmInfo?.fallback_provider
                  ? `(Fallback: ${llmInfo.fallback_provider})`
                  : ""}
              </div>
            </div>
          </div>
        </div>

        {/* Section C: Active Execution */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-zinc-400 text-xs">
              <span className="font-semibold uppercase tracking-wider text-[10px]">
                Current Task
              </span>
              <Activity className="w-4 h-4 text-amber-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium text-zinc-100 text-sm capitalize">
                  {taskId ? status.replace("_", " ") : "Idle"}
                </span>
              </div>
              <div className="text-xs font-mono text-zinc-500 mt-1 truncate">
                {taskId
                  ? `ID: ${taskId.slice(0, 8)} (${events.length} events)`
                  : "No task active"}
              </div>
            </div>
          </div>
        </div>

        {/* Section D: Workspaces Count */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-zinc-400 text-xs">
              <span className="font-semibold uppercase tracking-wider text-[10px]">
                Workspaces
              </span>
              <FolderTree className="w-4 h-4 text-blue-400" />
            </div>
            <div>
              <div className="font-medium text-zinc-100 text-sm">
                {workspaces.length} Registered
              </div>
              <div className="text-xs font-mono text-zinc-500 mt-1">
                Active project root paths
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Model Capabilities & Active Task Details */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-6 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
          <h2 className="text-sm font-semibold text-zinc-200 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-cyan-400" />
            <span>Active Model Capabilities</span>
          </h2>
          {llmInfo ? (
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(llmInfo.capabilities || {}).map(
                ([key, enabled]) => (
                  <div
                    key={key}
                    className={`flex items-center justify-between p-2.5 rounded-lg border font-mono ${
                      enabled
                        ? "bg-zinc-950/80 border-zinc-700 text-zinc-200"
                        : "bg-zinc-950/30 border-zinc-800 text-zinc-600"
                    }`}
                  >
                    <span className="capitalize">
                      {key.replace("supports_", "").replace("_", " ")}
                    </span>
                    {enabled ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <span className="text-[10px] text-zinc-600">
                        Disabled
                      </span>
                    )}
                  </div>
                ),
              )}
            </div>
          ) : (
            <p className="text-xs text-zinc-500 font-mono">
              No capabilities loaded.
            </p>
          )}
        </div>

        <div className="lg:col-span-6 bg-zinc-900 border border-zinc-800 rounded-xl p-5 flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-zinc-200 flex items-center gap-2">
              <Activity className="w-4 h-4 text-amber-400" />
              <span>Active Agent Task</span>
            </h2>
            {taskId ? (
              <div className="space-y-2 text-xs">
                <div className="p-3 bg-zinc-950 rounded-lg border border-zinc-800 space-y-1">
                  <div className="text-zinc-300 font-medium">
                    Task ID:{" "}
                    <span className="font-mono text-zinc-100">{taskId}</span>
                  </div>
                  <div className="text-zinc-400">
                    State:{" "}
                    <span className="capitalize font-mono text-zinc-200">
                      {status}
                    </span>
                  </div>
                  <div className="text-zinc-500 font-mono">
                    {events.length} lifecycle events recorded
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-6 text-center space-y-2 bg-zinc-950/40 rounded-lg border border-zinc-800">
                <p className="text-xs font-medium text-zinc-300">
                  No task running
                </p>
                <p className="text-xs text-zinc-500">
                  Initiate a prompt and target workspace from the Execution tab.
                </p>
              </div>
            )}
          </div>

          <button
            onClick={() => {
              window.location.hash = "home";
            }}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-100 text-xs font-medium border border-zinc-700 transition-colors"
          >
            <span>
              {taskId ? "Open Active Task in Execution" : "Go to Execution"}
            </span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
