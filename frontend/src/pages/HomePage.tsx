import React, { useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Code2,
  FileCheck,
  FileCode2,
  FileText,
  Layers,
  Loader2,
  Search,
  ShieldAlert,
  TestTube2,
  Wrench,
} from "lucide-react";
import { ApprovalGate } from "../components/ApprovalGate";
import { CodeWorkspace } from "../components/CodeWorkspace";
import { DiffViewer } from "../components/DiffViewer";
import { FinalResult } from "../components/FinalResult";
import { ReviewOutcome } from "../components/ReviewOutcome";
import { TaskForm } from "../components/TaskForm";
import { TestResults } from "../components/TestResults";
import { Timeline } from "../components/Timeline";
import { useTaskExecution } from "../context/TaskContext";

type WorkspaceTab = "stage" | "editor" | "diff" | "timeline" | "evidence";

export const HomePage: React.FC = () => {
  const {
    taskId,
    activeWorkspaceId,
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
    connectionState,
    handleStartTask,
    handleApprove,
    handleReject,
  } = useTaskExecution();

  const [activeTab, setActiveTab] = useState<WorkspaceTab>("stage");

  const hasEvent = (type: string) => events.some((e) => e.type === type);
  const repairCount = events.filter((e) => e.type === "repair_started").length;

  // Derive a single mutually exclusive active step
  let activeStepId: string | null = null;
  if (status === "awaiting_approval") {
    activeStepId = "approve";
  } else if (status === "running") {
    for (let i = events.length - 1; i >= 0; i--) {
      const type = events[i].type;
      if (type === "review_started" || type === "test_passed") {
        activeStepId = "review";
        break;
      }
      if (type === "repair_started" || type === "test_failed") {
        activeStepId = "repair";
        break;
      }
      if (type === "test_started" || type === "patch_applied") {
        activeStepId = "test";
        break;
      }
      if (type === "coding") {
        activeStepId = "code";
        break;
      }
      if (type === "planning" || type === "workspace_inspected") {
        activeStepId = "plan";
        break;
      }
      if (type === "task_started") {
        activeStepId = "inspect";
        break;
      }
    }
    if (!activeStepId) activeStepId = "inspect";
  }

  const isSuccessful = status === "completed";
  const isFailed = status === "failed" || status === "aborted";

  const PIPELINE_STEPS = [
    {
      id: "inspect",
      label: "Inspect",
      icon: Search,
      isDone:
        hasEvent("workspace_inspected") ||
        hasEvent("planning") ||
        hasEvent("coding") ||
        isSuccessful,
      isActive: activeStepId === "inspect",
    },
    {
      id: "plan",
      label: "Plan",
      icon: FileText,
      isDone:
        (hasEvent("planning") || hasEvent("coding")) &&
        activeStepId !== "plan" &&
        activeStepId !== "inspect",
      isActive: activeStepId === "plan",
    },
    {
      id: "code",
      label: "Code",
      icon: Code2,
      isDone:
        (hasEvent("coding") || hasEvent("patch_applied")) &&
        activeStepId !== "code" &&
        activeStepId !== "plan" &&
        activeStepId !== "inspect",
      isActive: activeStepId === "code",
    },
    {
      id: "approve",
      label: "Approve",
      icon: FileCheck,
      isDone:
        hasEvent("patch_applied") ||
        (!hasEvent("approval_required") &&
          (hasEvent("test_started") || isSuccessful)),
      isActive: activeStepId === "approve",
    },
    {
      id: "test",
      label: "Test",
      icon: TestTube2,
      isDone: hasEvent("test_passed"),
      isActive: activeStepId === "test",
      isFailed:
        isFailed && (hasEvent("test_failed") || activeStepId === "test"),
    },
    ...(repairCount > 0
      ? [
          {
            id: "repair",
            label: `Repair (${repairCount})`,
            icon: Wrench,
            isDone: hasEvent("test_passed") && activeStepId !== "repair",
            isActive: activeStepId === "repair",
            isFailed: isFailed && activeStepId === "repair",
          },
        ]
      : []),
    {
      id: "review",
      label: "Review",
      icon: ShieldAlert,
      isDone: hasEvent("review_started") && isSuccessful,
      isActive: activeStepId === "review",
    },
    {
      id: "finalize",
      label: "Finalize",
      icon: CheckCircle2,
      isDone: isSuccessful,
      isActive: false,
      isFailed: isFailed,
    },
  ];

  return (
    <div className="space-y-4">
      {/* Top Compact Execution Summary Header */}
      {taskId && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 shadow-lg">
          <div className="flex items-center gap-3">
            <div
              className={`p-2 rounded-lg ${
                status === "completed"
                  ? "bg-emerald-950/40 border border-emerald-800/50 text-emerald-400"
                  : status === "awaiting_approval"
                    ? "bg-amber-950/40 border border-amber-800/50 text-amber-400"
                    : status === "failed" || status === "aborted"
                      ? "bg-rose-950/40 border border-rose-800/50 text-rose-400"
                      : "bg-cyan-950/40 border border-cyan-800/50 text-cyan-400"
              }`}
            >
              <Activity
                className={`w-4 h-4 ${status === "running" ? "animate-pulse" : ""}`}
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
                  Task Execution
                </span>
                <span className="font-mono text-xs text-zinc-200 bg-zinc-950 px-2 py-0.5 rounded border border-zinc-800 font-semibold">
                  {taskId}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-zinc-400 font-mono">Status:</span>
                <span
                  className={`text-[11px] font-mono uppercase tracking-wider px-2 py-0.5 rounded font-semibold ${
                    status === "completed"
                      ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/60"
                      : status === "awaiting_approval"
                        ? "bg-amber-950/60 text-amber-400 border border-amber-800/60"
                        : status === "failed" || status === "aborted"
                          ? "bg-rose-950/60 text-rose-400 border border-rose-800/60"
                          : "bg-cyan-950/60 text-cyan-400 border border-cyan-800/60"
                  }`}
                >
                  {status.replace("_", " ")}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="bg-zinc-950 px-3 py-1.5 rounded-lg border border-zinc-800/80 flex items-center gap-2">
              <span className="text-zinc-500">Repairs:</span>
              <span
                className={`font-semibold ${
                  repairCount > 0 ? "text-amber-400" : "text-zinc-300"
                }`}
              >
                {repairCount} / 3
              </span>
            </div>

            <div className="bg-zinc-950 px-3 py-1.5 rounded-lg border border-zinc-800/80 flex items-center gap-2">
              <span className="text-zinc-500">Channel:</span>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    connectionState === "connected"
                      ? "bg-emerald-400 animate-pulse"
                      : connectionState === "reconnecting"
                        ? "bg-amber-400 animate-pulse"
                        : "bg-zinc-600"
                  }`}
                />
                <span className="text-zinc-300 capitalize">
                  {connectionState}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Grid: Pipeline Pane (Left) & Focused Workspace (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT PANE: Agent Lifecycle Pipeline */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-emerald-400" />
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
                    className={`flex items-center gap-3 p-2.5 rounded-lg text-xs font-mono transition-all ${
                      step.isActive
                        ? step.id === "approve"
                          ? "bg-amber-950/30 border border-amber-500/60 text-amber-300 shadow-sm shadow-amber-950/20"
                          : "bg-cyan-950/30 border border-cyan-500/60 text-cyan-300 shadow-sm shadow-cyan-950/20"
                        : step.isDone
                          ? "bg-emerald-950/20 text-emerald-400 border border-emerald-800/40"
                          : step.isFailed
                            ? "bg-rose-950/40 border border-rose-800 text-rose-300"
                            : "bg-zinc-950/30 text-zinc-500 border border-zinc-800/50"
                    }`}
                  >
                    <div className="flex items-center justify-center w-5 h-5 shrink-0">
                      {step.isActive ? (
                        <Loader2
                          className={`w-4 h-4 animate-spin ${
                            step.id === "approve"
                              ? "text-amber-400"
                              : "text-cyan-400"
                          }`}
                        />
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
                      <span
                        className={`ml-auto text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded font-bold ${
                          step.id === "approve"
                            ? "bg-amber-900/60 text-amber-200 border border-amber-700/60 animate-pulse"
                            : "bg-cyan-900/60 text-cyan-200 border border-cyan-700/60 animate-pulse"
                        }`}
                      >
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
                  <span className="text-zinc-300">{repairCount} / 3</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT PANE: Focused Execution Workspace */}
        <div className="lg:col-span-8 space-y-4 flex flex-col">
          {!taskId ? (
            <div className="space-y-4">
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-4">
                <div>
                  <h2 className="text-base font-semibold text-zinc-100">
                    Initiate Code Agent Task
                  </h2>
                  <p className="text-xs text-zinc-400 mt-1">
                    Select a registered workspace and specify technical
                    implementation instructions.
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

              {activeWorkspaceId && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-xs font-mono text-zinc-400 px-1">
                    <Code2 className="w-3.5 h-3.5 text-indigo-400" />
                    <span className="uppercase tracking-wider font-semibold">
                      Workspace Explorer & Editor
                    </span>
                  </div>
                  <CodeWorkspace workspaceId={activeWorkspaceId} />
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4 flex-1 flex flex-col">
              {/* Workspace Navigation Tabs */}
              <div className="flex items-center gap-2 border-b border-zinc-800 pb-2">
                <button
                  onClick={() => setActiveTab("stage")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    activeTab === "stage"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Active Stage
                </button>
                <button
                  onClick={() => setActiveTab("editor")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${
                    activeTab === "editor"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <Code2 className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Code Workspace</span>
                </button>
                <button
                  onClick={() => setActiveTab("diff")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${
                    activeTab === "diff"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <span>Unified Diff</span>
                  {pendingPatch && (
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  )}
                </button>
                <button
                  onClick={() => setActiveTab("timeline")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    activeTab === "timeline"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Event Trace ({events.length})
                </button>
                <button
                  onClick={() => setActiveTab("evidence")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${
                    activeTab === "evidence"
                      ? "bg-zinc-800 text-zinc-100 font-semibold"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <span>Verification Evidence</span>
                  {testResult && (
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        testResult.exit_code === 0
                          ? "bg-emerald-400"
                          : "bg-rose-400"
                      }`}
                    />
                  )}
                </button>
              </div>

              {/* Tab 1: Active Stage */}
              {activeTab === "stage" && (
                <div className="space-y-4 flex-1">
                  {status === "awaiting_approval" && (
                    <div className="space-y-4">
                      <ApprovalGate
                        coderSummary={coderSummary}
                        pendingPatch={pendingPatch}
                        onApprove={handleApprove}
                        onReject={handleReject}
                        isSubmitting={isSubmittingApproval}
                      />
                      {pendingPatch && (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-xs text-zinc-400 font-mono">
                            <span className="flex items-center gap-1.5">
                              <FileCode2 className="w-3.5 h-3.5 text-emerald-400" />
                              Proposed Workspace Patch
                            </span>
                            <button
                              onClick={() => setActiveTab("diff")}
                              className="text-emerald-400 hover:text-emerald-300 underline"
                            >
                              Expand in Diff Viewer →
                            </button>
                          </div>
                          <DiffViewer patch={pendingPatch} />
                        </div>
                      )}
                    </div>
                  )}

                  {status === "running" && (
                    <div className="space-y-4">
                      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3 shadow-lg">
                        <div className="flex items-center gap-3">
                          <Loader2 className="w-5 h-5 text-cyan-400 animate-spin shrink-0" />
                          <div>
                            <h3 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider font-mono">
                              Agent Graph Executing:{" "}
                              {activeStepId?.toUpperCase() || "PROCESSING"}
                            </h3>
                            <p className="text-xs text-zinc-400 mt-0.5">
                              Analyzing repository workspace, executing LLM
                              inference, and maintaining sandbox barriers.
                            </p>
                          </div>
                        </div>
                        <div className="pt-2 border-t border-zinc-800 flex items-center justify-between text-xs font-mono text-zinc-500">
                          <span>Recent Milestone:</span>
                          <span className="text-zinc-300 truncate max-w-xs">
                            {events.length > 0
                              ? events[events.length - 1].title ||
                                events[events.length - 1].type
                              : "Graph initialized"}
                          </span>
                        </div>
                      </div>
                      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 max-h-[480px] overflow-y-auto">
                        <Timeline events={events} />
                      </div>
                    </div>
                  )}

                  {(status === "completed" ||
                    status === "failed" ||
                    status === "aborted" ||
                    finalResult) && (
                    <div className="space-y-4">
                      <FinalResult result={finalResult} error={error} />
                      {testResult && <TestResults testResult={testResult} />}
                      {reviewResult && <ReviewOutcome review={reviewResult} />}
                    </div>
                  )}

                  {isFailed && !finalResult && (
                    <div className="bg-rose-950/30 border border-rose-800/70 text-rose-200 rounded-xl p-5 space-y-3">
                      <div className="flex items-center gap-2 font-semibold text-sm text-rose-300">
                        <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
                        <span>Task Execution Terminated with Failure</span>
                      </div>
                      <p className="text-xs font-mono text-rose-300/90 leading-relaxed whitespace-pre-wrap">
                        {error ||
                          "An unrecoverable failure occurred during execution."}
                      </p>
                      {testResult && (
                        <div className="pt-2 border-t border-rose-900/40">
                          <TestResults testResult={testResult} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: Code Workspace */}
              {activeTab === "editor" && (
                <div className="space-y-4 flex-1">
                  <CodeWorkspace workspaceId={activeWorkspaceId} />
                </div>
              )}

              {/* Tab 3: Unified Diff */}
              {activeTab === "diff" && (
                <div className="space-y-3">
                  <DiffViewer patch={pendingPatch} />
                </div>
              )}

              {/* Tab 4: Event Trace */}
              {activeTab === "timeline" && (
                <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex-1 max-h-[620px] overflow-y-auto">
                  <Timeline events={events} />
                </div>
              )}

              {/* Tab 5: Verification Evidence */}
              {activeTab === "evidence" && (
                <div className="space-y-4">
                  {testResult || reviewResult ? (
                    <>
                      {testResult && <TestResults testResult={testResult} />}
                      {reviewResult && <ReviewOutcome review={reviewResult} />}
                    </>
                  ) : (
                    <div className="bg-zinc-950 border border-zinc-800 rounded-xl p-8 text-center text-xs font-mono text-zinc-500">
                      No sandbox test or quality review evidence recorded for
                      this task yet.
                    </div>
                  )}
                </div>
              )}

              {error && status !== "completed" && !finalResult && !isFailed && (
                <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs">
                  <span className="font-semibold">Error: </span>
                  {error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
