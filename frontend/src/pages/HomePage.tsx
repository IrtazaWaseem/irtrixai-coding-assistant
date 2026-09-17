import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  FileCheck,
  FileText,
  Loader2,
  Search,
  ShieldAlert,
  TestTube2,
  Wrench,
} from "lucide-react";
import { TaskForm } from "../components/TaskForm";
import { Timeline } from "../components/Timeline";
import { ApprovalGate } from "../components/ApprovalGate";
import { TestResults } from "../components/TestResults";
import { ReviewOutcome } from "../components/ReviewOutcome";
import { FinalResult } from "../components/FinalResult";
import { useTaskExecution } from "../context/TaskContext";

export const HomePage: React.FC = () => {
  const {
    taskId,
    status,
    events,
    pendingPatch,
    coderSummary,
    testResult,
    reviewResult,
    finalResult,
    error,
    isLoading,
    isSubmittingApproval,
    handleStartTask,
    handleApprove,
    handleReject,
  } = useTaskExecution();

  const [activeTab, setActiveTab] = useState<
    "primary" | "timeline" | "evidence"
  >("primary");

  const hasEvent = (type: string) => events.some((e) => e.type === type);
  const repairCount = events.filter((e) => e.type === "repair_started").length;

  const PIPELINE_STEPS = [
    {
      id: "inspect",
      label: "Inspect",
      icon: Search,
      isDone: hasEvent("workspace_inspected") || hasEvent("planning"),
      isActive: status === "running" && !hasEvent("workspace_inspected"),
    },
    {
      id: "plan",
      label: "Plan",
      icon: FileText,
      isDone:
        hasEvent("planning") &&
        (hasEvent("coding") || hasEvent("approval_required")),
      isActive:
        status === "running" &&
        hasEvent("workspace_inspected") &&
        !hasEvent("planning"),
    },
    {
      id: "code",
      label: "Code",
      icon: Code2,
      isDone:
        (hasEvent("coding") || hasEvent("patch_applied")) &&
        status !== "running",
      isActive:
        status === "running" &&
        hasEvent("planning") &&
        !hasEvent("approval_required"),
    },
    {
      id: "approve",
      label: "Approve",
      icon: FileCheck,
      isDone: hasEvent("patch_applied") || hasEvent("approval_submitted"),
      isActive: status === "awaiting_approval",
    },
    {
      id: "test",
      label: "Test",
      icon: TestTube2,
      isDone: hasEvent("test_passed") || hasEvent("test_failed"),
      isActive:
        status === "running" &&
        hasEvent("patch_applied") &&
        !hasEvent("test_passed") &&
        !hasEvent("test_failed"),
    },
    ...(repairCount > 0
      ? [
          {
            id: "repair",
            label: `Repair (${repairCount})`,
            icon: Wrench,
            isDone: hasEvent("test_passed") && repairCount > 0,
            isActive: status === "running" && hasEvent("repair_started"),
          },
        ]
      : []),
    {
      id: "review",
      label: "Review",
      icon: ShieldAlert,
      isDone: hasEvent("review_started") && status === "completed",
      isActive: status === "running" && hasEvent("review_started"),
    },
    {
      id: "finalize",
      label: "Finalize",
      icon: CheckCircle2,
      isDone: status === "completed",
      isActive: false,
      isFailed: status === "failed" || status === "aborted",
    },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* LEFT PANE: Agent Lifecycle Pipeline */}
      <div className="lg:col-span-4 space-y-4">
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                Agent Pipeline
              </h2>
              <p className="text-[11px] text-zinc-500 mt-0.5">
                Supervised Execution Lifecycle
              </p>
            </div>
            {taskId && (
              <span className="font-mono text-[10px] text-zinc-400 bg-zinc-950 px-2 py-0.5 rounded border border-zinc-800">
                {taskId.slice(0, 8)}
              </span>
            )}
          </div>

          <div className="space-y-2">
            {PIPELINE_STEPS.map((step, idx) => {
              const Icon = step.icon;
              return (
                <div
                  key={step.id}
                  className={`flex items-center gap-3 p-2 rounded-lg text-xs font-mono transition-all ${
                    step.isActive
                      ? "bg-blue-950/50 border border-blue-800 text-blue-300 shadow-sm"
                      : step.isDone
                        ? "bg-zinc-950/40 text-emerald-400 border border-zinc-800/80"
                        : step.isFailed
                          ? "bg-rose-950/50 border border-rose-800 text-rose-300"
                          : "text-zinc-600 border border-transparent"
                  }`}
                >
                  <div className="flex items-center justify-center w-5 h-5 shrink-0">
                    {step.isActive ? (
                      <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                    ) : step.isDone ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    ) : step.isFailed ? (
                      <AlertTriangle className="w-4 h-4 text-rose-400" />
                    ) : (
                      <span className="text-[10px] text-zinc-600 font-bold">
                        {idx + 1}
                      </span>
                    )}
                  </div>
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  <span className="font-medium">{step.label}</span>
                  {step.isActive && (
                    <span className="ml-auto text-[10px] uppercase tracking-wider bg-blue-900/60 px-1.5 py-0.2 rounded text-blue-200">
                      Active
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {taskId && (
            <div className="pt-3 border-t border-zinc-800 text-[11px] font-mono text-zinc-500 space-y-1">
              <div className="flex justify-between">
                <span>Total Events:</span>
                <span className="text-zinc-300">{events.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Repairs Triggered:</span>
                <span className="text-zinc-300">{repairCount}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT PANE: Execution Surface */}
      <div className="lg:col-span-8 space-y-4 flex flex-col">
        {!taskId ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-zinc-100">
                Initiate Code Agent Task
              </h2>
              <p className="text-xs text-zinc-400 mt-1">
                Provide an absolute workspace root path and specific technical
                objective.
              </p>
            </div>
            <TaskForm onSubmit={handleStartTask} isLoading={isLoading} />
            {error && (
              <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs">
                <span className="font-semibold">Error: </span>
                {error}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4 flex-1 flex flex-col">
            <div className="flex items-center gap-2 border-b border-zinc-800 pb-2">
              <button
                onClick={() => setActiveTab("primary")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  activeTab === "primary"
                    ? "bg-zinc-800 text-zinc-100 font-semibold"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {status === "awaiting_approval"
                  ? "Proposed Patch"
                  : status === "completed" || status === "failed"
                    ? "Final Result"
                    : "Active Execution"}
              </button>
              <button
                onClick={() => setActiveTab("timeline")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  activeTab === "timeline"
                    ? "bg-zinc-800 text-zinc-100 font-semibold"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                Timeline ({events.length})
              </button>
              {(testResult || reviewResult) && (
                <button
                  onClick={() => setActiveTab("evidence")}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    activeTab === "evidence"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Verification Evidence
                </button>
              )}
            </div>

            {activeTab === "primary" && (
              <div className="space-y-4 flex-1">
                {status === "awaiting_approval" && (
                  <div className="space-y-4">
                    <div className="bg-amber-950/20 border border-amber-800/80 p-4 rounded-xl flex items-center justify-between">
                      <div className="flex items-center gap-2 text-amber-300 text-xs font-medium">
                        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                        <span>
                          Operator Confirmation Required before Filesystem
                          Mutation
                        </span>
                      </div>
                    </div>
                    <ApprovalGate
                      coderSummary={coderSummary}
                      pendingPatch={pendingPatch}
                      onApprove={handleApprove}
                      onReject={handleReject}
                      isSubmitting={isSubmittingApproval}
                    />
                  </div>
                )}

                {(status === "completed" ||
                  status === "failed" ||
                  finalResult) && (
                  <div className="space-y-4">
                    <FinalResult result={finalResult} error={error} />
                    {testResult && <TestResults testResult={testResult} />}
                    {reviewResult && <ReviewOutcome review={reviewResult} />}
                  </div>
                )}

                {status === "running" && (
                  <div className="space-y-4">
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex items-center gap-3">
                      <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                      <div className="text-xs">
                        <span className="font-semibold text-zinc-100">
                          Agent executing sandbox lifecycle...
                        </span>
                        <p className="text-zinc-500 font-mono text-[11px] mt-0.5">
                          Follow live stream in the timeline tab or review
                          events below.
                        </p>
                      </div>
                    </div>
                    <div className="max-h-[520px] overflow-y-auto">
                      <Timeline events={events} />
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === "timeline" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex-1 max-h-[620px] overflow-y-auto">
                <Timeline events={events} />
              </div>
            )}

            {activeTab === "evidence" && (
              <div className="space-y-4">
                {testResult && <TestResults testResult={testResult} />}
                {reviewResult && <ReviewOutcome review={reviewResult} />}
              </div>
            )}

            {error && status !== "completed" && !finalResult && (
              <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs">
                <span className="font-semibold">Error: </span>
                {error}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
