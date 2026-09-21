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
  XCircle,
  Zap,
} from "lucide-react";
import { getLLMInfo, getSystemStatus, getWorkspaces } from "../services/api";
import {
  LLMInfoResponse,
  SystemStatusResponse,
  TaskAnalyticsResponse,
  WorkspaceResponse,
} from "../types";
import { useTaskExecution } from "../context/TaskContext";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const DashboardPage: React.FC = () => {
  const { taskId, status, events, tokenUsage } = useTaskExecution();

  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(
    null,
  );
  const [llmInfo, setLlmInfo] = useState<LLMInfoResponse | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [analytics, setAnalytics] = useState<TaskAnalyticsResponse | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sys, llm, ws, anRes] = await Promise.all([
        getSystemStatus(),
        getLLMInfo(),
        getWorkspaces(),
        fetch(`${API_BASE}/api/v1/tasks/analytics`)
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null),
      ]);
      setSystemStatus(sys);
      setLlmInfo(llm);
      setWorkspaces(ws);
      setAnalytics(anRes);
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

  const getStatusBadge = () => {
    if (!taskId) {
      return (
        <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">
          Idle
        </span>
      );
    }
    switch (status) {
      case "completed":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/60">
            Completed
          </span>
        );
      case "awaiting_approval":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-800/60 animate-pulse">
            Awaiting Approval
          </span>
        );
      case "running":
        return (
          <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-cyan-950/60 text-cyan-400 border border-cyan-800/60 animate-pulse">
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
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100">System Telemetry</h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Operational runtime parameters, token analytics, and workspace
            status.
          </p>
        </div>
        <button
          onClick={fetchDashboardData}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-300 hover:text-zinc-100 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 transition-colors disabled:opacity-50"
        >
          <RotateCw
            className={`w-3.5 h-3.5 ${isLoading ? "animate-spin text-cyan-400" : ""}`}
          />
          <span>Refresh</span>
        </button>
      </div>

      {error && (
        <div className="bg-rose-950/30 border border-rose-800/70 text-rose-300 p-4 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span className="font-mono">{error}</span>
          </div>
          <button
            onClick={fetchDashboardData}
            className="underline hover:text-rose-200 font-semibold ml-4"
          >
            Retry
          </button>
        </div>
      )}

      {/* Primary Telemetry Grid: 5-Card Dashboard */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* 1. Backend Orchestrator */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between space-y-3 shadow-md">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
              Backend Server
            </span>
            <Server className="w-4 h-4 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  isHealthy ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
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
            <div className="text-[11px] font-mono text-zinc-500 mt-1 truncate">
              v{systemStatus?.version || "—"} · Env:{" "}
              {systemStatus?.environment || "—"}
            </div>
          </div>
        </div>

        {/* 2. LLM Gateway */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between space-y-3 shadow-md">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
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
            <div className="text-[11px] font-mono text-zinc-500 mt-1 truncate capitalize">
              Provider: {llmInfo?.provider || "—"}
              {llmInfo?.fallback_provider
                ? ` (Fallback: ${llmInfo.fallback_provider})`
                : ""}
            </div>
          </div>
        </div>

        {/* 3. Token Consumption Telemetry (Requirement M) */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between space-y-3 shadow-md">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
              Token Consumption
            </span>
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <div className="font-medium text-zinc-100 text-sm font-mono">
              {analytics ? analytics.total_tokens.toLocaleString() : "0"} Total
            </div>
            <div className="text-[11px] font-mono text-zinc-500 mt-1">
              In: {analytics ? analytics.prompt_tokens.toLocaleString() : "0"} ·
              Out:{" "}
              {analytics ? analytics.completion_tokens.toLocaleString() : "0"} (
              {analytics?.llm_calls || 0} calls)
            </div>
          </div>
        </div>

        {/* 4. Current Task */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between space-y-3 shadow-md">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
              Current Task
            </span>
            <Activity className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">{getStatusBadge()}</div>
            <div className="text-[11px] font-mono text-zinc-500 mt-1.5 truncate">
              {taskId
                ? `ID: ${taskId.slice(0, 8)} (${events.length} events)`
                : "No task active"}
            </div>
          </div>
        </div>

        {/* 5. Registered Workspaces */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col justify-between space-y-3 shadow-md">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
              Workspaces
            </span>
            <FolderTree className="w-4 h-4 text-emerald-400" />
          </div>
          <div>
            <div className="font-medium text-zinc-100 text-sm">
              {workspaces.length} Registered
            </div>
            <div className="text-[11px] font-mono text-zinc-500 mt-1">
              Active project root paths
            </div>
          </div>
        </div>
      </div>

      {/* Model Capabilities & Active Execution Scope */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Capabilities Matrix */}
        <div className="lg:col-span-6 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300 flex items-center gap-2 font-mono">
              <Cpu className="w-4 h-4 text-cyan-400" />
              <span>Model Gateway Capabilities</span>
            </h2>
            <span className="text-[11px] font-mono text-zinc-500 capitalize">
              {llmInfo?.provider || "—"}
            </span>
          </div>

          {llmInfo?.capabilities &&
          Object.keys(llmInfo.capabilities).length > 0 ? (
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(llmInfo.capabilities).map(([key, enabled]) => (
                <div
                  key={key}
                  className={`flex items-center justify-between p-2.5 rounded-lg border font-mono transition-colors ${
                    enabled
                      ? "bg-zinc-950/80 border-zinc-800 text-zinc-200"
                      : "bg-zinc-950/30 border-zinc-900 text-zinc-600"
                  }`}
                >
                  <span className="capitalize text-[11px]">
                    {key.replace("supports_", "").replace(/_/g, " ")}
                  </span>
                  {enabled ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-zinc-700 shrink-0" />
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-zinc-500 font-mono">
              {isLoading
                ? "Querying gateway capabilities..."
                : "No capabilities reported by gateway."}
            </div>
          )}
        </div>

        {/* Active Task Summary Card */}
        <div className="lg:col-span-6 bg-zinc-900 border border-zinc-800 rounded-xl p-5 flex flex-col justify-between space-y-4 shadow-lg">
          <div className="space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300 flex items-center gap-2 font-mono">
                <Activity className="w-4 h-4 text-amber-400" />
                <span>Active Agent Execution</span>
              </h2>
              {getStatusBadge()}
            </div>

            {taskId ? (
              <div className="space-y-2.5 text-xs">
                <div className="p-3 bg-zinc-950 rounded-lg border border-zinc-800/80 space-y-1.5 font-mono">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Task UUID:</span>
                    <span className="text-zinc-200 font-semibold">
                      {taskId}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Status:</span>
                    <span className="text-zinc-300 uppercase">{status}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Checkpoints Logged:</span>
                    <span className="text-cyan-400 font-semibold">
                      {events.length}
                    </span>
                  </div>
                  {tokenUsage && (
                    <div className="flex justify-between items-center pt-1 border-t border-zinc-900">
                      <span className="text-zinc-500">Tokens Consumed:</span>
                      <span className="text-amber-400 font-semibold">
                        {tokenUsage.total_tokens.toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>

                {events.length > 0 && (
                  <div className="text-[11px] font-mono text-zinc-500 truncate">
                    Latest event:{" "}
                    <span className="text-zinc-300">
                      {events[events.length - 1].title ||
                        events[events.length - 1].type}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-6 text-center space-y-2 bg-zinc-950/40 rounded-lg border border-zinc-800/60">
                <p className="text-xs font-medium text-zinc-300">
                  No active task in progress
                </p>
                <p className="text-[11px] text-zinc-500">
                  Initiate execution instructions from the primary Execution
                  Studio.
                </p>
              </div>
            )}
          </div>

          <button
            onClick={() => {
              window.location.hash = "home";
            }}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-zinc-800/80 hover:bg-zinc-800 text-zinc-100 text-xs font-medium border border-zinc-700/60 transition-colors"
          >
            <span>
              {taskId
                ? "Open Active Task in Execution Studio"
                : "Go to Execution Studio"}
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-emerald-400" />
          </button>
        </div>
      </div>
    </div>
  );
};
