import React from "react";
import { History } from "lucide-react";

export const HistoryPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">Run History</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Inspect past agent runs, execution timelines, and verification
          evidence.
        </p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
          <History className="w-4 h-4 text-purple-400" />
          <span>Historical Audit Index</span>
        </div>
        <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl">
          Queries known task IDs via{" "}
          <code className="text-zinc-200">
            GET /api/v1/tasks/&#123;id&#125;
          </code>{" "}
          using the client-indexed history storage. Phase 2D will render task
          selector cards with persistent checkpoint records.
        </p>
      </div>
    </div>
  );
};
