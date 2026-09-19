import React from "react";
import {
  Check,
  Info,
  Lock,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

export const GovernancePage: React.FC = () => {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-zinc-100">
          Governance & Safety Policies
        </h1>
        <p className="text-xs text-zinc-400 mt-0.5">
          Architectural isolation boundaries, authorization gates, and runtime
          security specifications.
        </p>
      </div>

      {/* Explicit Architectural Specification Banner */}
      <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-3.5 flex items-start gap-3">
        <Info className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <div className="text-xs text-zinc-400 leading-relaxed font-mono">
          <span className="text-zinc-200 font-semibold">
            Architectural Enforcement Specifications:{" "}
          </span>
          The safety properties documented below are invariant constraints
          enforced directly by the backend runtime, Docker sandbox, and
          LangGraph checkpoint engine. This view outlines policy rules, not live
          telemetry probes.
        </div>
      </div>

      {/* 4-Card Governance Matrix */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Policy 1: Container Containment */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div className="flex items-center gap-2.5 text-zinc-200 text-sm font-semibold">
              <div className="p-2 rounded-lg bg-emerald-950/40 border border-emerald-800/40 text-emerald-400">
                <ShieldCheck className="w-4 h-4" />
              </div>
              <div>
                <span className="block">Docker Sandbox Isolation</span>
                <span className="text-[10px] font-mono font-normal text-zinc-500">
                  Container Security Profile
                </span>
              </div>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-zinc-950 text-zinc-400 px-2 py-0.5 rounded border border-zinc-800">
              Enforced by Runtime
            </span>
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
              <span>Unprivileged sandbox user execution (UID 1000)</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>All Linux capabilities dropped (--cap-drop=ALL)</span>
            </li>
          </ul>
        </div>

        {/* Policy 2: Human-in-the-Loop Gate */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div className="flex items-center gap-2.5 text-zinc-200 text-sm font-semibold">
              <div className="p-2 rounded-lg bg-amber-950/40 border border-amber-800/40 text-amber-400">
                <ShieldAlert className="w-4 h-4" />
              </div>
              <div>
                <span className="block">Human-in-the-Loop Gate</span>
                <span className="text-[10px] font-mono font-normal text-zinc-500">
                  LangGraph Checkpoint Interrupt
                </span>
              </div>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-zinc-950 text-amber-400/90 px-2 py-0.5 rounded border border-amber-900/40">
              Enforced by Graph
            </span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2.5 font-mono">
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Mandatory operator consent before filesystem mutation</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Unified diff preview required prior to write actions</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>
                Optional guidance feedback channel on proposal rejection
              </span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Non-bypassable pause enforcing explicit confirmation</span>
            </li>
          </ul>
        </div>

        {/* Policy 3: Execution Boundaries & Limits */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div className="flex items-center gap-2.5 text-zinc-200 text-sm font-semibold">
              <div className="p-2 rounded-lg bg-cyan-950/40 border border-cyan-800/40 text-cyan-400">
                <RotateCcw className="w-4 h-4" />
              </div>
              <div>
                <span className="block">Execution Boundaries & Limits</span>
                <span className="text-[10px] font-mono font-normal text-zinc-500">
                  Repair Budget Controls
                </span>
              </div>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-zinc-950 text-cyan-400/90 px-2 py-0.5 rounded border border-cyan-900/40">
              Enforced by Budget
            </span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2.5 font-mono">
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>
                Automated repair loop bounded strictly to max 3 cycles
              </span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Fail-closed evaluation on unverified test exits</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>
                Pytest cache disabled (-p no:cacheprovider) on :ro mounts
              </span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>
                Transactional checkpoint recovery backed by PostgreSQL 16
              </span>
            </li>
          </ul>
        </div>

        {/* Policy 4: Workspace & Secret Protection */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div className="flex items-center gap-2.5 text-zinc-200 text-sm font-semibold">
              <div className="p-2 rounded-lg bg-blue-950/40 border border-blue-800/40 text-blue-400">
                <Lock className="w-4 h-4" />
              </div>
              <div>
                <span className="block">Workspace & Secret Protection</span>
                <span className="text-[10px] font-mono font-normal text-zinc-500">
                  Filesystem Barriers
                </span>
              </div>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider bg-zinc-950 text-blue-400/90 px-2 py-0.5 rounded border border-blue-900/40">
              Enforced by Engine
            </span>
          </div>
          <ul className="text-xs text-zinc-400 space-y-2.5 font-mono">
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span>
                Protected file safeguards active (.env, .git, alembic.ini)
              </span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span>Path traversal and symlink boundary validation</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span>Credential redaction for PostgreSQL URIs and LLM keys</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span>Zero client-side API key custody (FastAPI-mediated)</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};
