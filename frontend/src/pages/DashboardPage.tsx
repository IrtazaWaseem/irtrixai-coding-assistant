import React from "react";
import { Activity, Cpu, Server } from "lucide-react";

export const DashboardPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">System Dashboard</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Runtime environment, LLM gateway health, and active task status.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
            <Server className="w-4 h-4 text-emerald-400" />
            <span>Backend Status</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Consumes <code className="text-zinc-200">GET /api/v1/status</code>{" "}
            to report backend uptime, version, and environment settings.
          </p>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
            <Cpu className="w-4 h-4 text-cyan-400" />
            <span>LLM Gateway</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Consumes <code className="text-zinc-200">GET /api/v1/llm/info</code>{" "}
            to display primary model, fallback provider, and capabilities.
          </p>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
            <Activity className="w-4 h-4 text-amber-400" />
            <span>Active Task Metrics</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Displays real-time repair counter, checkpoint latency, and execution
            state of current task.
          </p>
        </div>
      </div>
    </div>
  );
};
