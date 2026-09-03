import { useEffect, useState } from "react";
import {
  Terminal,
  Bot,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import axios from "axios";

interface BackendHealth {
  status: string;
  service: string;
  version: string;
}

export default function App(): JSX.Element {
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const checkHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<BackendHealth>(
        "http://localhost:8000/health",
      );
      setHealth(response.data);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to connect to backend",
      );
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <div className="flex h-screen flex-col bg-slate-950 font-sans text-slate-100">
      <header className="flex h-14 items-center justify-between border-b border-slate-800 bg-slate-900/60 px-6 backdrop-blur">
        <div className="flex items-center gap-3">
          <Bot className="h-6 w-6 text-blue-400" />
          <span className="font-semibold tracking-tight text-white">
            IrtrixAI Coding Assistant
          </span>
          <span className="rounded bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-400 border border-blue-500/20">
            Day 1: Scaffold
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={checkHealth}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-slate-700 disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            Recheck API
          </button>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium text-white">System Status</h2>
            <span className="text-xs text-slate-400">
              Target Stack Verification
            </span>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex items-center gap-2.5">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                <span className="text-sm font-medium text-slate-200">
                  Frontend Shell
                </span>
              </div>
              <span className="text-xs text-emerald-400 font-mono">
                React 18 + Vite Running
              </span>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex items-center gap-2.5">
                {health ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                ) : (
                  <AlertCircle className="h-5 w-5 text-amber-400" />
                )}
                <div>
                  <div className="text-sm font-medium text-slate-200">
                    Backend API (/health)
                  </div>
                  {health && (
                    <div className="text-xs text-slate-400">
                      {health.service} v{health.version}
                    </div>
                  )}
                </div>
              </div>
              <div className="text-right">
                {loading ? (
                  <span className="text-xs text-slate-400 font-mono">
                    Checking...
                  </span>
                ) : health ? (
                  <span className="text-xs text-emerald-400 font-mono">
                    200 OK
                  </span>
                ) : (
                  <span className="text-xs text-amber-400 font-mono">
                    {error || "Disconnected"}
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex items-center gap-2.5">
                <Terminal className="h-5 w-5 text-blue-400" />
                <span className="text-sm font-medium text-slate-200">
                  Monorepo Modules
                </span>
              </div>
              <span className="text-xs text-slate-400 font-mono">
                Zustand, Monaco, xterm Loaded
              </span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
