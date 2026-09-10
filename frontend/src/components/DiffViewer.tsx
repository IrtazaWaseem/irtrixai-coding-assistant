import React, { useState } from "react";

interface DiffViewerProps {
  patch: string;
}

interface ParsedLine {
  type: "add" | "delete" | "hunk" | "header" | "context";
  text: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ patch }) => {
  const [copied, setCopied] = useState(false);

  if (!patch || !patch.trim()) {
    return (
      <div className="text-xs text-zinc-500 italic p-4 bg-zinc-950 rounded-lg border border-zinc-800">
        No diff content generated.
      </div>
    );
  }

  const parseLines = (rawDiff: string): ParsedLine[] => {
    return rawDiff.split("\n").map((line) => {
      if (
        line.startsWith("+++ ") ||
        line.startsWith("--- ") ||
        line.startsWith("diff ")
      ) {
        return { type: "header", text: line };
      }
      if (line.startsWith("@@")) {
        return { type: "hunk", text: line };
      }
      if (line.startsWith("+")) {
        return { type: "add", text: line };
      }
      if (line.startsWith("-")) {
        return { type: "delete", text: line };
      }
      return { type: "context", text: line };
    });
  };

  const lines = parseLines(patch);

  const handleCopy = () => {
    navigator.clipboard.writeText(patch);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden text-xs font-mono">
      <div className="bg-zinc-900 px-4 py-2 border-b border-zinc-800 flex justify-between items-center text-zinc-400">
        <span>Unified Diff ({lines.length} lines)</span>
        <button
          onClick={handleCopy}
          className="text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="max-h-96 overflow-auto p-2 divide-y divide-zinc-900/50">
        {lines.map((l, idx) => {
          let lineClasses = "px-2 py-0.5 whitespace-pre select-text ";
          if (l.type === "add") {
            lineClasses += "bg-emerald-950/40 text-emerald-300";
          } else if (l.type === "delete") {
            lineClasses += "bg-rose-950/40 text-rose-300";
          } else if (l.type === "hunk") {
            lineClasses += "bg-sky-950/30 text-sky-400 font-semibold";
          } else if (l.type === "header") {
            lineClasses += "text-zinc-500 font-semibold";
          } else {
            lineClasses += "text-zinc-400";
          }

          return (
            <div key={idx} className={lineClasses}>
              {l.text}
            </div>
          );
        })}
      </div>
    </div>
  );
};
