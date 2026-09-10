import React from "react";

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
  const getStatusBadge = () => {
    const s = status.toLowerCase();
    switch (s) {
      case "running":
        return "bg-sky-950 text-sky-400 border-sky-800";
      case "awaiting_approval":
        return "bg-amber-950 text-amber-400 border-amber-800 animate-pulse";
      case "completed":
        return "bg-emerald-950 text-emerald-400 border-emerald-800";
      case "failed":
      case "cancelled":
        return "bg-rose-950 text-rose-400 border-rose-800";
      default:
        return "bg-zinc-800 text-zinc-400 border-zinc-700";
    }
  };

  return (
    <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur-sm sticky top-0 z-30 px-6 py-4 flex items-center justify-between">
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
            IX
          </div>
          <h1 className="text-lg font-semibold tracking-tight text-zinc-100">
            IrtrixAI{" "}
            <span className="text-zinc-500 font-normal">Coding Assistant</span>
          </h1>
        </div>

        {taskId && (
          <div className="hidden sm:flex items-center space-x-2 text-xs font-mono bg-zinc-950 px-2.5 py-1 rounded border border-zinc-800 text-zinc-400">
            <span className="text-zinc-600">ID:</span>
            <span>{taskId.slice(0, 8)}...</span>
          </div>
        )}
      </div>

      <div className="flex items-center space-x-3">
        {taskId && (
          <>
            <span
              className={`text-xs px-2.5 py-1 rounded-full border font-medium uppercase tracking-wider ${getStatusBadge()}`}
            >
              {status.replace("_", " ")}
            </span>

            <div className="hidden md:flex items-center space-x-1.5 text-xs text-zinc-500">
              <span
                className={`w-2 h-2 rounded-full ${
                  connectionState === "connected"
                    ? "bg-emerald-500"
                    : connectionState === "reconnecting"
                      ? "bg-amber-500 animate-ping"
                      : "bg-zinc-600"
                }`}
              />
              <span className="capitalize">{connectionState}</span>
            </div>

            <button
              onClick={onReset}
              className="text-xs px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors border border-zinc-700"
            >
              New Task
            </button>
          </>
        )}
      </div>
    </header>
  );
};
