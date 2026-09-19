import React, { useState } from "react";
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Loader2,
  MessageSquare,
  FileCode,
} from "lucide-react";

export interface ApprovalGateProps {
  coderSummary?: string | null;
  pendingPatch?: string | null;
  onApprove: () => Promise<void> | void;
  onReject: (feedback: string) => Promise<void> | void;
  isSubmitting: boolean;
}

export const ApprovalGate: React.FC<ApprovalGateProps> = ({
  coderSummary,
  pendingPatch,
  onApprove,
  onReject,
  isSubmitting,
}) => {
  const [feedback, setFeedback] = useState("");
  const [showFeedback, setShowFeedback] = useState(false);

  // Extract modified filenames from the unified diff patch text
  const targetFiles: string[] = [];
  if (pendingPatch) {
    const lines = pendingPatch.split("\n");
    for (const line of lines) {
      if (line.startsWith("+++ b/")) {
        const file = line.replace("+++ b/", "").trim();
        if (file && !targetFiles.includes(file)) {
          targetFiles.push(file);
        }
      }
    }
  }

  const handleConfirmReject = () => {
    onReject(feedback.trim());
  };

  return (
    <div className="bg-zinc-900 border-2 border-amber-500/40 rounded-xl p-5 shadow-2xl space-y-4">
      {/* Alert Header */}
      <div className="flex items-start gap-3.5">
        <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 shrink-0">
          <ShieldAlert className="w-6 h-6 animate-pulse" />
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-zinc-100">
              Operator Approval Required
            </h3>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded border border-amber-500/30">
              Human-in-the-Loop
            </span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            The autonomous coder has generated modifications for your workspace.
            Review the unified diff below carefully before granting filesystem
            write permission.
          </p>
        </div>
      </div>

      {/* Coder Strategy Summary */}
      {coderSummary && (
        <div className="bg-zinc-950/80 border border-zinc-800 rounded-lg p-3.5 space-y-1.5">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
            Proposed Strategy
          </span>
          <p className="text-xs text-zinc-300 font-mono leading-relaxed whitespace-pre-wrap">
            {coderSummary}
          </p>
        </div>
      )}

      {/* Target Files Affected */}
      {targetFiles.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <span className="text-zinc-500 font-medium">Mutating files:</span>
          {targetFiles.map((file, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 font-mono text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded"
            >
              <FileCode className="w-3 h-3" />
              {file}
            </span>
          ))}
        </div>
      )}

      {/* Optional Feedback Input on Rejection */}
      {showFeedback && (
        <div className="space-y-2 pt-1">
          <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
            <MessageSquare className="w-3.5 h-3.5 text-zinc-400" />
            Guidance for the Debugger (Optional):
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. Ensure type annotations are preserved, or handle empty array edge cases..."
            className="w-full bg-zinc-950 border border-zinc-700 rounded-lg p-2.5 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-amber-500"
            rows={2}
            disabled={isSubmitting}
          />
        </div>
      )}

      {/* Decision Action Buttons */}
      <div className="flex items-center justify-end gap-3 pt-2 border-t border-zinc-800/80">
        {!showFeedback ? (
          <button
            onClick={() => setShowFeedback(true)}
            disabled={isSubmitting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium text-rose-300 hover:text-rose-100 bg-rose-950/30 hover:bg-rose-950/60 border border-rose-800/40 transition-colors disabled:opacity-50"
          >
            <XCircle className="w-4 h-4" />
            Reject Changes
          </button>
        ) : (
          <button
            onClick={handleConfirmReject}
            disabled={isSubmitting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium text-rose-200 bg-rose-900/80 hover:bg-rose-900 border border-rose-700 transition-colors disabled:opacity-50"
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <XCircle className="w-4 h-4" />
            )}
            Confirm Rejection
          </button>
        )}

        <button
          onClick={onApprove}
          disabled={isSubmitting}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-xs font-semibold text-emerald-950 bg-emerald-400 hover:bg-emerald-300 shadow-lg shadow-emerald-900/30 transition-all disabled:opacity-50"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-emerald-950" />
              <span>Applying Patch...</span>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-4 h-4 text-emerald-950" />
              <span>Approve & Continue</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
