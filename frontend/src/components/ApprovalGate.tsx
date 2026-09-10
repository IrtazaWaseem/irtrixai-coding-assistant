import React, { useState } from "react";
import { DiffViewer } from "./DiffViewer";

interface ApprovalGateProps {
  coderSummary?: string | null;
  pendingPatch?: string | null;
  onApprove: () => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
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
  const [showDiff, setShowDiff] = useState(true);

  return (
    <div className="bg-zinc-900 border-2 border-amber-600/40 rounded-xl p-6 shadow-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="w-3 h-3 rounded-full bg-amber-500 animate-ping" />
          <h2 className="text-base font-semibold text-amber-300 tracking-tight">
            Human Approval Required
          </h2>
        </div>
        <span className="text-xs text-amber-500 font-mono bg-amber-950/80 px-2.5 py-0.5 rounded border border-amber-800">
          Operator Consent Gate
        </span>
      </div>

      {coderSummary && (
        <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-3.5">
          <p className="text-xs font-semibold uppercase text-zinc-500 mb-1">
            Coder Proposal Summary
          </p>
          <p className="text-sm text-zinc-200">{coderSummary}</p>
        </div>
      )}

      {pendingPatch && (
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-xs font-medium text-zinc-400">
              Pending Code Modifications
            </span>
            <button
              onClick={() => setShowDiff(!showDiff)}
              className="text-xs text-indigo-400 hover:text-indigo-300"
            >
              {showDiff ? "Collapse Diff" : "Expand Diff"}
            </button>
          </div>
          {showDiff && <DiffViewer patch={pendingPatch} />}
        </div>
      )}

      <div>
        <label
          htmlFor="operator-feedback"
          className="block text-xs font-medium text-zinc-400 mb-1"
        >
          Operator Feedback (Required on rejection, optional on approval)
        </label>
        <textarea
          id="operator-feedback"
          rows={2}
          disabled={isSubmitting}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="e.g. Please refine edge case handling for zero input."
          className="w-full px-3.5 py-2 text-xs bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-amber-500 transition-colors"
        />
      </div>

      <div className="flex items-center justify-end space-x-3 pt-2">
        <button
          onClick={() => onReject(feedback)}
          disabled={isSubmitting}
          className="px-4 py-2 text-xs font-medium rounded-lg bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800 disabled:opacity-50 transition-colors"
        >
          {isSubmitting ? "Submitting..." : "Reject Changes"}
        </button>

        <button
          onClick={onApprove}
          disabled={isSubmitting}
          className="px-5 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20 disabled:opacity-50 transition-all"
        >
          {isSubmitting ? "Applying & Resuming..." : "Approve & Continue"}
        </button>
      </div>
    </div>
  );
};
