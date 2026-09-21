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
  isTerminalOpen?: boolean;
  onToggleTerminal?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  taskId,
  status,
  connectionState,
  onReset,
  isTerminalOpen,
  onToggleTerminal,
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
        return "bg-cyan-950/60 text-cyan-300 border-cyan-700/60 shadow-sm shadow-cyan-950/20";
      case "awaiting_approval":
        return "bg-amber-950/60 text-amber-300 border-amber-600/70 animate-pulse shadow-sm shadow-amber-950/20";
      case "completed":
        return "bg-emerald-950/60 text-emerald-300 border-emerald-800/60";
      case "failed":
      case "aborted":
        return "bg-rose-950/60 text-rose-300 border-rose-800/60";
      default:
        return "bg-zinc-900 text-zinc-300 border-zinc-700/80";
    }
  };

  return (
    <header className="border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur-md px-4 sm:px-6 py-2.5 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
        {/* Brand & Technical Identity */}
        <div className="flex items-center gap-3 sm:gap-4 shrink-0">
          <button
            onClick={onToggleTerminal}
            className="flex items-center gap-2.5 hover:opacity-90 transition-opacity text-left cursor-pointer group"
            title={
              isTerminalOpen
                ? "Close Sandbox Terminal"
                : "Open Sandbox Terminal"
            }
          >
            <div
              className={`w-8 h-8 rounded-lg border flex items-center justify-center transition-colors shadow-inner ${
                isTerminalOpen
                  ? "bg-emerald-950 border-emerald-500 text-emerald-300"
                  : "bg-zinc-900 border-zinc-700/70 text-zinc-100 group-hover:border-zinc-500"
              }`}
            >
              <Terminal className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="flex items-center">
              <span className="font-bold tracking-tight text-sm text-zinc-100 font-mono">
                IRTRIX<span className="text-emerald-400">AI</span>
              </span>
              <span className="hidden md:inline-block text-[10px] text-zinc-400 font-mono ml-2.5 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 tracking-wider">
                OPERATIONS CONSOLE
              </span>
            </div>
          </button>

          {/* Backend Health Telemetry Pill */}
          <div className="hidden sm:flex items-center border-l border-zinc-800/80 pl-3 sm:pl-4">
            {backendHealthy === null ? (
              <span className="flex items-center gap-1.5 text-xs text-zinc-400 font-mono bg-zinc-900/60 px-2.5 py-1 rounded-md border border-zinc-800/80">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span>Connecting</span>
              </span>
            ) : backendHealthy ? (
              <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-mono bg-emerald-950/30 px-2.5 py-1 rounded-md border border-emerald-800/40">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span>Backend healthy</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-rose-400 font-mono bg-rose-950/30 px-2.5 py-1 rounded-md border border-rose-800/50">
                <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                <span>Backend unreachable</span>
              </span>
            )}
          </div>
        </div>

        {/* Active Task Telemetry & Actions */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {/* Terminal Toggle Button in Action Bar */}
          {onToggleTerminal && (
            <button
              onClick={onToggleTerminal}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-medium border transition-colors shadow-sm cursor-pointer ${
                isTerminalOpen
                  ? "bg-emerald-950/60 text-emerald-300 border-emerald-600/70 shadow-emerald-950/30"
                  : "text-zinc-300 hover:text-zinc-100 bg-zinc-900 hover:bg-zinc-800 border-zinc-800 hover:border-zinc-700"
              }`}
              title={
                isTerminalOpen
                  ? "Close Sandbox Terminal"
                  : "Open Embedded Sandbox Terminal"
              }
            >
              <Terminal
                className={`w-3.5 h-3.5 ${
                  isTerminalOpen ? "text-emerald-400" : "text-zinc-400"
                }`}
              />
              <span className="hidden sm:inline">Terminal</span>
            </button>
          )}

          {/* Active Task Link */}
          {taskId && (
            <button
              onClick={() => {
                window.location.hash = "home";
              }}
              className={`flex items-center gap-2 px-2.5 py-1 rounded-lg text-xs font-mono border transition-all hover:opacity-90 ${getStatusBadge()}`}
              title="View active task in Execution Studio"
            >
              <span className="capitalize font-semibold">
                {status.replace("_", " ")}
              </span>
              <span className="opacity-40">·</span>
              <span className="text-zinc-200 font-bold">
                {taskId.slice(0, 8)}
              </span>
            </button>
          )}

          {/* Connection Channel State */}
          {connectionState !== "idle" && (
            <div className="hidden lg:flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded-md bg-zinc-900/60 border border-zinc-800/80 text-zinc-400">
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

          {/* New Task / Reset Action */}
          {taskId && (
            <button
              onClick={onReset}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-mono font-medium text-zinc-300 hover:text-zinc-100 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 transition-colors shadow-sm"
              title="Reset active execution and start a new task"
            >
              <RotateCcw className="w-3 h-3 text-zinc-400" />
              <span className="hidden sm:inline">New Task</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
