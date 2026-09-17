import React from "react";
import { Check, Lock, ShieldCheck } from "lucide-react";

export const GovernancePage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">
          Governance & Safety Policies
        </h1>
        <p className="text-xs text-zinc-400 mt-0.5">
          Enforced isolation boundaries, authorization gates, and credential
          protection rules.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Container Boundaries */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-200 text-sm font-semibold">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Docker Sandbox Isolation</span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2.5 font-mono">
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Host workspace mounted read-only (:ro)</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Network isolation active (--network=none)</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Unprivileged sandbox user (UID 1000)</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Linux capabilities dropped (--cap-drop=ALL)</span>
            </li>
          </ul>
        </div>

        {/* Human-in-the-Loop & Invariants */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-200 text-sm font-semibold">
            <Lock className="w-4 h-4 text-amber-400" />
            <span>Execution Invariants</span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2.5 font-mono">
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Mandatory operator approval before disk mutation</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Repair loop bounded strictly to max 3 cycles</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Credential redaction for PostgreSQL URIs and LLM keys</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Protected file safeguards active (.env, .git)</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};
