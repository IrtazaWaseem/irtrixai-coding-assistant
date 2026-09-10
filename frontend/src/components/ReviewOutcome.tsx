import React from "react";
import { ReviewResult } from "../types";

interface ReviewOutcomeProps {
  review?: ReviewResult | null;
}

export const ReviewOutcome: React.FC<ReviewOutcomeProps> = ({ review }) => {
  if (!review) return null;

  const isApproved = review.verdict === "approved";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-xl space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Automated Code Audit
        </h2>
        <span
          className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${
            isApproved
              ? "bg-emerald-950 text-emerald-400 border-emerald-800"
              : "bg-rose-950 text-rose-400 border-rose-800"
          }`}
        >
          {review.verdict.replace("_", " ").toUpperCase()}
        </span>
      </div>

      <p className="text-xs text-zinc-300 leading-relaxed">{review.summary}</p>

      {review.issues && review.issues.length > 0 && (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold text-rose-400 uppercase">
            Issues Identified:
          </p>
          <ul className="list-disc list-inside text-xs text-zinc-400 space-y-0.5">
            {review.issues.map((iss, i) => (
              <li key={i}>{iss}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
