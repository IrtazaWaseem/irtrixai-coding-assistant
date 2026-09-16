import React from "react";
import { Lock, ShieldCheck } from "lucide-react";

export const GovernancePage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">
          Governance & Security Policy
        </h1>
        <p className="text-xs text-zinc-400 mt-1">
          Verify runtime isolation, HITL approval enforcement, and sandbox
          safety invariants.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Sandbox Boundaries</span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2 list-disc list-inside">
            <li>
              Host workspace mounted strictly read-only (
              <code className="text-zinc-300">:ro</code>)
            </li>
            <li>
              Network isolation enforced (
              <code className="text-zinc-300">--network=none</code>)
            </li>
            <li>
              Unprivileged non-root container user (
              <code className="text-zinc-300">UID 1000</code>)
            </li>
            <li>
              All Linux capabilities dropped (
              <code className="text-zinc-300">--cap-drop=ALL</code>)
            </li>
          </ul>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
            <Lock className="w-4 h-4 text-amber-400" />
            <span>Agent Governance Rules</span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2 list-disc list-inside">
            <li>
              Zero filesystem mutation permitted without explicit operator
              approval
            </li>
            <li>Repair cycles strictly bounded to a maximum of 3 attempts</li>
            <li>
              Secret redaction active for PostgreSQL URIs and LLM credentials
            </li>
            <li>
              Protected file safeguards active (
              <code className="text-zinc-300">.env</code>,{" "}
              <code className="text-zinc-300">.git</code>)
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};
