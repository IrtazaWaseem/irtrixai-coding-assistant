import React from "react";
import { FinalResult as FinalResultType } from "../types";

interface FinalResultProps {
  result?: FinalResultType | null;
  error?: string | null;
}

export const FinalResult: React.FC<FinalResultProps> = ({ result, error }) => {
  if (!result && !error) return null;

  const isSuccess = result?.status === "completed";

  return (
    <div
      className={`rounded-xl p-6 border shadow-xl ${
        isSuccess
          ? "bg-emerald-950/20 border-emerald-800/80 text-emerald-200"
          : "bg-rose-950/20 border-rose-800/80 text-rose-200"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider">
          {isSuccess
            ? "Task Completed Successfully"
            : "Task Execution Terminated"}
        </h2>
        <span className="text-xs font-mono font-bold uppercase">
          {result?.status || "FAILED"}
        </span>
      </div>

      <p className="text-xs leading-relaxed opacity-90">
        {result?.summary || error || "Task concluded with errors."}
      </p>

      {result?.files_changed && result.files_changed.length > 0 && (
        <div className="mt-3 text-xs">
          <span className="text-zinc-400 font-medium">Files Mutated: </span>
          <span className="font-mono text-zinc-300">
            {result.files_changed.join(", ")}
          </span>
        </div>
      )}
    </div>
  );
};
