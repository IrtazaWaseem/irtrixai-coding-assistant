import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  RotateCcw,
  Terminal,
} from "lucide-react";
import { getSystemStatus } from "../services/api";

interface HeaderProps {
  taskId: string | null;
  status: string;
  connectionState: "connected" | "reconnecting" | "disconnected" | "idle";
  onReset: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  taskId,
  status,
  connectionState,
  onReset,
}) => {
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let isMounted = true;

    const checkHealth = () => {
      getSystemStatus()
        .then((res) => {
          if (isMounted) {
            const s = res.status?.toLowerCase();
            const isOk = s === "active" || s === "healthy" || s === "ok";
            setBackendHealthy(isOk);
          }
        })
        .catch(() => {
          if (isMounted) setBackendHealthy(false);
        });
    };

    checkHealth();
    const intervalId = window.setInterval(checkHealth, 20000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const getStatusBadge = () => {
    switch (status.toLowerCase()) {
      case "running":
        return "bg-blue-950/80 text-blue-300 border-blue-800";
      case "awaiting_approval":
        return "bg-amber-950/80 text-amber-300 border-amber-800 animate-pulse";
      case "completed":
        return "bg-emerald-950/80 text-emerald-300 border-emerald-800";
      case "failed":
      case "aborted":
        return "bg-rose-950/80 text-rose-300 border-rose-800";
      default:
        return "bg-zinc-900 text-zinc-400 border-zinc-800";
    }
  };

  return (
    <header className="border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md px-6 py-3">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Brand & Telemetry */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-zinc-900 border border-zinc-700 flex items-center justify-center text-zinc-100 shadow-sm">
              <Terminal className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <span className="font-bold tracking-tight text-sm text-zinc-100 font-mono">
                IRTRIX<span className="text-emerald-400">AI</span>
              </span>
              <span className="hidden sm:inline-block text-[10px] text-zinc-500 font-mono ml-2 border border-zinc-800 rounded px-1.5 py-0.5">
                AGENT WORKSPACE
              </span>
            </div>
          </div>

          {/* Persistent Backend Health */}
          <div className="hidden md:flex items-center gap-2 border-l border-zinc-800 pl-4">
            {backendHealthy === null ? (
              <span className="flex items-center gap-1.5 text-xs text-zinc-500 font-mono">
                <span className="w-2 h-2 rounded-full bg-zinc-600 animate-pulse" />
                Connecting...
              </span>
            ) : backendHealthy ? (
              <span className="flex items-center gap-1.5 text-xs text-zinc-400 font-mono">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                Backend healthy
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-rose-400 font-mono">
                <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                Backend unreachable
              </span>
            )}
          </div>
        </div>

        {/* Task Meta & Controls */}
        <div className="flex items-center gap-3">
          {taskId && (
            <button
              onClick={() => {
                window.location.hash = "home";
              }}
              className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-mono border transition-all ${getStatusBadge()}`}
              title="Click to view task in Execution workspace"
            >
              <span className="capitalize font-semibold">
                {status.replace("_", " ")}
              </span>
              <span className="opacity-50">·</span>
              <span className="text-zinc-300">{taskId.slice(0, 8)}</span>
            </button>
          )}

          {connectionState !== "idle" && (
            <div className="hidden sm:flex items-center gap-1.5 text-xs font-mono text-zinc-400">
              <Activity
                className={`w-3.5 h-3.5 ${
                  connectionState === "connected"
                    ? "text-emerald-400"
                    : connectionState === "reconnecting"
                      ? "text-amber-400 animate-spin"
                      : "text-zinc-600"
                }`}
              />
              <span className="capitalize">{connectionState}</span>
            </div>
          )}

          {taskId && (
            <button
              onClick={onReset}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 border border-zinc-800 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              <span>New Task</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
