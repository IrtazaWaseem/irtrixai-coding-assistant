import React, { useState } from "react";
import { FileCode, Copy, Check } from "lucide-react";

export interface DiffViewerProps {
  patch: string | null;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ patch }) => {
  const [copied, setCopied] = useState(false);

  if (!patch || !patch.trim()) {
    return (
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-6 text-center text-zinc-500 text-xs font-mono">
        No code modifications proposed in this stage.
      </div>
    );
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(patch);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lines = patch.split("\n");

  let additions = 0;
  let deletions = 0;
  let detectedFileName = "";

  for (const line of lines) {
    if (line.startsWith("+++ b/")) {
      detectedFileName = line.replace("+++ b/", "").trim();
    } else if (line.startsWith("+") && !line.startsWith("+++")) {
      additions++;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      deletions++;
    }
  }

  let oldLineNum = 0;
  let newLineNum = 0;

  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded-lg overflow-hidden shadow-xl">
      {/* Diff Header */}
      <div className="bg-zinc-900 px-4 py-2.5 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <FileCode className="w-4 h-4 text-emerald-400" />
          <span className="text-sm font-mono font-medium text-zinc-200">
            {detectedFileName || "Proposed Changes"}
          </span>
          <div className="flex items-center gap-1.5 text-xs font-mono ml-2">
            <span className="text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/40">
              +{additions}
            </span>
            <span className="text-rose-400 bg-rose-950/60 px-2 py-0.5 rounded border border-rose-800/40">
              -{deletions}
            </span>
          </div>
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-zinc-400 hover:text-zinc-100 bg-zinc-800/60 hover:bg-zinc-800 rounded border border-zinc-700/50 transition-colors"
          title="Copy unified diff"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400 font-mono">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span className="font-mono">Copy Diff</span>
            </>
          )}
        </button>
      </div>

      {/* Unified Diff Table with Line Gutters */}
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto font-mono text-xs select-text">
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, idx) => {
              const isChunkHeader = line.startsWith("@@");
              const isAddition =
                line.startsWith("+") && !line.startsWith("+++");
              const isDeletion =
                line.startsWith("-") && !line.startsWith("---");
              const isFileHeader =
                line.startsWith("---") || line.startsWith("+++");

              if (isChunkHeader) {
                const match = line.match(
                  /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/,
                );
                if (match) {
                  oldLineNum = parseInt(match[1], 10);
                  newLineNum = parseInt(match[2], 10);
                }
              } else if (isAddition) {
                newLineNum++;
              } else if (isDeletion) {
                oldLineNum++;
              } else if (!isFileHeader) {
                oldLineNum++;
                newLineNum++;
              }

              let rowBg = "hover:bg-zinc-900/40";
              let textClass = "text-zinc-300";
              let gutterBg = "bg-zinc-950 text-zinc-600";

              if (isChunkHeader) {
                rowBg = "bg-cyan-950/20 text-cyan-400 font-semibold";
                gutterBg = "bg-cyan-950/40 text-cyan-500";
              } else if (isAddition) {
                rowBg = "bg-emerald-950/25 text-emerald-200";
                gutterBg =
                  "bg-emerald-950/50 text-emerald-400 border-r border-emerald-900/40";
              } else if (isDeletion) {
                rowBg = "bg-rose-950/25 text-rose-200";
                gutterBg =
                  "bg-rose-950/50 text-rose-400 border-r border-rose-900/40";
              } else if (isFileHeader) {
                rowBg = "bg-zinc-900/70 text-zinc-400 font-bold";
              }

              return (
                <tr
                  key={idx}
                  className={`${rowBg} transition-colors leading-relaxed`}
                >
                  {/* Old Line Number Gutter */}
                  <td
                    className={`w-10 px-2 py-0.5 text-right select-none ${gutterBg} border-r border-zinc-800/80`}
                  >
                    {!isFileHeader && !isChunkHeader
                      ? isAddition
                        ? ""
                        : oldLineNum - 1
                      : ""}
                  </td>
                  {/* New Line Number Gutter */}
                  <td
                    className={`w-10 px-2 py-0.5 text-right select-none ${gutterBg} border-r border-zinc-800/80`}
                  >
                    {!isFileHeader && !isChunkHeader
                      ? isDeletion
                        ? ""
                        : newLineNum - 1
                      : ""}
                  </td>
                  {/* +/- Sign Indicator */}
                  <td className="w-5 text-center select-none font-bold text-zinc-500">
                    {isAddition ? "+" : isDeletion ? "-" : ""}
                  </td>
                  {/* Code Content */}
                  <td className={`px-2 py-0.5 whitespace-pre ${textClass}`}>
                    {line.slice(isAddition || isDeletion ? 1 : 0) || " "}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
