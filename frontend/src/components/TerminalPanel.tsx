import React, { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Clock,
  CornerDownLeft,
  HardDrive,
  Loader2,
  Maximize2,
  Minimize2,
  Terminal as TerminalIcon,
  Trash2,
  X,
} from "lucide-react";
import { executeTerminalCommand } from "../services/api";
import { TerminalExecutionResponse } from "../types";

interface TerminalPanelProps {
  isOpen: boolean;
  onClose: () => void;
  activeWorkspaceId: string | null;
}

interface CommandLogItem {
  id: string;
  timestamp: string;
  workspaceId: string;
  command: string;
  result?: TerminalExecutionResponse;
  error?: string;
  isLoading?: boolean;
}

export const TerminalPanel: React.FC<TerminalPanelProps> = ({
  isOpen,
  onClose,
  activeWorkspaceId,
}) => {
  const [logs, setLogs] = useState<CommandLogItem[]>([]);
  const [commandInput, setCommandInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  // In-memory command history for Up/Down navigation
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);

  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Auto-scroll on new entries
  useEffect(() => {
    if (isOpen) {
      logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, isOpen]);

  // Focus input on panel open
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleRunCommand = async () => {
    const trimmed = commandInput.trim();
    if (!trimmed || isRunning) return;

    if (!activeWorkspaceId) {
      const entryId = `${Date.now()}-${Math.random()}`;
      setLogs((prev) => [
        ...prev,
        {
          id: entryId,
          timestamp: new Date().toLocaleTimeString(),
          workspaceId: "none",
          command: trimmed,
          error: "Select a workspace before running a command.",
        },
      ]);
      setCommandInput("");
      return;
    }

    const currentWs = activeWorkspaceId;
    const entryId = `${Date.now()}-${Math.random()}`;

    // Add to history
    setHistory((prev) => [...prev, trimmed]);
    setHistoryIndex(-1);

    // Append loading log entry
    setLogs((prev) => [
      ...prev,
      {
        id: entryId,
        timestamp: new Date().toLocaleTimeString(),
        workspaceId: currentWs,
        command: trimmed,
        isLoading: true,
      },
    ]);

    setCommandInput("");
    setIsRunning(true);

    try {
      const res = await executeTerminalCommand(currentWs, trimmed);
      setLogs((prev) =>
        prev.map((item) =>
          item.id === entryId
            ? { ...item, isLoading: false, result: res }
            : item,
        ),
      );
    } catch (err: any) {
      const errorMsg =
        err.details?.reason || err.message || "Terminal execution failed.";
      setLogs((prev) =>
        prev.map((item) =>
          item.id === entryId
            ? { ...item, isLoading: false, error: errorMsg }
            : item,
        ),
      );
    } finally {
      setIsRunning(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleRunCommand();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (history.length === 0) return;
      const nextIdx =
        historyIndex === -1
          ? history.length - 1
          : Math.max(0, historyIndex - 1);
      setHistoryIndex(nextIdx);
      setCommandInput(history[nextIdx] || "");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex === -1) return;
      const nextIdx = historyIndex + 1;
      if (nextIdx >= history.length) {
        setHistoryIndex(-1);
        setCommandInput("");
      } else {
        setHistoryIndex(nextIdx);
        setCommandInput(history[nextIdx] || "");
      }
    }
  };

  const handleClear = () => {
    setLogs([]);
    setHistoryIndex(-1);
  };

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 z-50 bg-zinc-950 border-t border-zinc-800 shadow-2xl flex flex-col font-mono transition-all duration-200 ${
        isExpanded ? "h-[80vh]" : "h-72 sm:h-80"
      }`}
    >
      {/* Terminal Title Bar */}
      <div className="bg-zinc-900/90 border-b border-zinc-800/80 px-4 py-2 flex items-center justify-between select-none">
        <div className="flex items-center gap-2.5 min-w-0">
          <TerminalIcon className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-xs font-semibold tracking-wider uppercase text-zinc-200">
            Sandbox Command Console
          </span>

          <span className="hidden sm:inline-block text-zinc-600">|</span>

          {/* Active Workspace Indicator */}
          {activeWorkspaceId ? (
            <div className="flex items-center gap-1 text-[11px] text-zinc-400 truncate bg-zinc-950 px-2 py-0.5 rounded border border-zinc-800">
              <HardDrive className="w-3 h-3 text-cyan-400 shrink-0" />
              <span className="text-zinc-500 hidden md:inline">workspace:</span>
              <span className="text-zinc-300 font-bold truncate">
                {activeWorkspaceId.slice(0, 8)}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1 text-[11px] text-amber-400 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/50">
              <AlertTriangle className="w-3 h-3 shrink-0" />
              <span>No workspace active</span>
            </div>
          )}
        </div>

        {/* Window Controls */}
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={handleClear}
            className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
            title="Clear output"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
            title={isExpanded ? "Restore height" : "Maximize panel"}
          >
            {isExpanded ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 rounded transition-colors"
            title="Close terminal"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Terminal Output Stream */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-black/90 text-xs text-zinc-300 selection:bg-emerald-900 selection:text-white">
        {logs.length === 0 ? (
          <div className="text-zinc-600 space-y-1 select-none">
            <p className="text-zinc-500 font-semibold">
              IRTRIXAI Ephemeral Docker Sandbox
            </p>
            <p className="text-[11px]">
              Strict isolation: --network=none, non-root user, read-only root,
              512MB RAM cap.
            </p>
            <p className="text-[11px] text-zinc-600">
              Supported commands: pytest -q, python -m pytest, ruff check ., git
              status, git diff
            </p>
          </div>
        ) : (
          logs.map((log) => (
            <div
              key={log.id}
              className="space-y-1.5 border-b border-zinc-900 pb-3"
            >
              {/* Command Invocation Header */}
              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                <div className="flex items-center gap-1.5">
                  <span className="text-emerald-400 font-bold">$</span>
                  <span className="text-zinc-100 font-semibold">
                    {log.command}
                  </span>
                </div>

                <div className="flex items-center gap-2 font-mono">
                  {log.result && (
                    <>
                      <span className="flex items-center gap-1 text-zinc-500 text-[10px]">
                        <Clock className="w-3 h-3" />
                        {log.result.duration_seconds ?? 0}s
                      </span>
                      <span
                        className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                          log.result.exit_code === 0
                            ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                            : "bg-rose-950 text-rose-400 border border-rose-800/60"
                        }`}
                      >
                        exit {log.result.exit_code}
                      </span>
                    </>
                  )}
                  <span className="text-zinc-600 text-[10px]">
                    {log.timestamp}
                  </span>
                </div>
              </div>

              {/* Running State */}
              {log.isLoading && (
                <div className="flex items-center gap-2 text-cyan-400 text-[11px] py-1">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Executing in sandbox container...</span>
                </div>
              )}

              {/* Execution Error Banner */}
              {log.error && (
                <div className="flex items-start gap-2 text-rose-400 bg-rose-950/30 border border-rose-900/60 p-2.5 rounded text-[11px]">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span className="whitespace-pre-wrap">{log.error}</span>
                </div>
              )}

              {/* Standard Output */}
              {log.result?.stdout && (
                <pre className="text-zinc-300 font-mono whitespace-pre-wrap break-all select-text pl-3 border-l-2 border-zinc-800 py-0.5">
                  {log.result.stdout}
                </pre>
              )}

              {/* Standard Error */}
              {log.result?.stderr && (
                <pre className="text-amber-300/90 font-mono whitespace-pre-wrap break-all select-text pl-3 border-l-2 border-amber-800/50 py-0.5">
                  {log.result.stderr}
                </pre>
              )}

              {/* Truncation Notice */}
              {log.result?.truncated && (
                <div className="text-[10px] text-amber-500/80 italic">
                  [output truncated at configured limit]
                </div>
              )}
            </div>
          ))
        )}
        <div ref={logsEndRef} />
      </div>

      {/* Terminal Input Bar */}
      <div className="bg-zinc-900/90 border-t border-zinc-800 px-3 py-2 flex items-center gap-2">
        <span className="text-emerald-400 font-bold text-sm select-none">
          $
        </span>
        <input
          ref={inputRef}
          type="text"
          value={commandInput}
          onChange={(e) => setCommandInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isRunning || !activeWorkspaceId}
          placeholder={
            !activeWorkspaceId
              ? "Select a workspace above before running commands..."
              : isRunning
                ? "Waiting for sandbox..."
                : "Enter command (e.g. pytest -q, ruff check .)"
          }
          className="flex-1 bg-transparent text-zinc-100 placeholder-zinc-600 text-xs focus:outline-none disabled:opacity-50 font-mono"
        />

        <button
          onClick={handleRunCommand}
          disabled={isRunning || !commandInput.trim() || !activeWorkspaceId}
          className="flex items-center gap-1 px-3 py-1 bg-emerald-500 hover:bg-emerald-400 text-emerald-950 rounded text-xs font-bold font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          title="Run command in sandbox (Enter)"
        >
          {isRunning ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <CornerDownLeft className="w-3 h-3" />
          )}
          <span>Run</span>
        </button>
      </div>
    </div>
  );
};
