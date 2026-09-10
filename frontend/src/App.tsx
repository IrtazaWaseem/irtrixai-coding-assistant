import React, { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { TaskForm } from "./components/TaskForm";
import { Timeline } from "./components/Timeline";
import { ApprovalGate } from "./components/ApprovalGate";
import { TestResults } from "./components/TestResults";
import { ReviewOutcome } from "./components/ReviewOutcome";
import { FinalResult } from "./components/FinalResult";
import {
  createTask,
  getTask,
  runTask,
  submitApproval,
  subscribeToEvents,
} from "./services/api";
import {
  ActivityEvent,
  FinalResult as FinalResultType,
  ReviewResult,
  TestResultData,
} from "./types";

export const App: React.FC = () => {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [pendingPatch, setPendingPatch] = useState<string | null>(null);
  const [coderSummary, setCoderSummary] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResultData | null>(null);
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null);
  const [finalResult, setFinalResult] = useState<FinalResultType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSubmittingApproval, setIsSubmittingApproval] =
    useState<boolean>(false);
  const [connectionState, setConnectionState] = useState<
    "connected" | "reconnecting" | "disconnected" | "idle"
  >("idle");

  // Push activity event helper
  const addEvent = (
    type: string,
    title: string,
    description?: string,
    statusType: "success" | "warning" | "error" | "info" = "info",
    metadata?: Record<string, any>,
  ) => {
    const newEvent: ActivityEvent = {
      id: `${Date.now()}-${Math.random()}`,
      timestamp: new Date().toLocaleTimeString(),
      type,
      title,
      description,
      status: statusType,
      metadata,
    };
    setEvents((prev) => [...prev, newEvent]);
  };

  // Restore task state on browser refresh without restarting execution
  useEffect(() => {
    const savedTaskId =
      new URLSearchParams(window.location.search).get("taskId") ||
      localStorage.getItem("irtrixai_active_task_id");

    if (savedTaskId) {
      setTaskId(savedTaskId);
      setIsLoading(true);
      getTask(savedTaskId)
        .then((t) => {
          const st = t.status.toLowerCase();
          setStatus(st);
          addEvent(
            "task_restored",
            `Restored existing task (${st})`,
            undefined,
            "info",
          );

          // Only observe via SSE if task is currently active
          if (st === "running" || st === "awaiting_approval") {
            connectSSE(t.id);
          }
        })
        .catch((err) => {
          console.warn("Could not restore saved task:", err);
          localStorage.removeItem("irtrixai_active_task_id");
        })
        .finally(() => setIsLoading(false));
    }
  }, []);

  // Safe observation-only SSE connection
  const connectSSE = (id: string) => {
    setConnectionState("connected");
    const unsubscribe = subscribeToEvents(
      id,
      (eventType, data) => {
        handleServerEvent(eventType, data);
      },
      (err) => {
        console.warn("SSE encountered a connection issue:", err);
        setConnectionState("reconnecting");
      },
    );

    return unsubscribe;
  };

  // Dispatch incoming SSE events into UI state
  const handleServerEvent = (eventType: string, data: any) => {
    switch (eventType) {
      case "task_started":
        setStatus("running");
        addEvent(eventType, "Agent Execution Started", undefined, "info");
        break;

      case "task_not_started":
        setStatus("pending");
        addEvent(eventType, "Task Pending Run Command", data.message, "info");
        break;

      case "workspace_inspected":
        addEvent(
          eventType,
          "Workspace Inspected",
          `Detected technologies: ${(data.tech_stack || []).join(", ")}`,
          "success",
          { tech_stack: data.tech_stack },
        );
        break;

      case "planning":
        addEvent(
          eventType,
          "Implementation Plan Formulated",
          data.plan_summary,
          "success",
        );
        break;

      case "coding":
        addEvent(
          eventType,
          "Code Modifications Proposed",
          `Target files: ${(data.files_changed || []).join(", ")}`,
          "info",
        );
        break;

      case "approval_required":
        setStatus("awaiting_approval");
        setPendingPatch(data.pending_patch || null);
        setCoderSummary(data.coder_summary || null);
        addEvent(
          eventType,
          "Operator Approval Required",
          "Waiting for human confirmation",
          "warning",
        );
        break;

      case "patch_applied":
        addEvent(
          eventType,
          "Approved Changes Applied to Workspace",
          undefined,
          "success",
        );
        break;

      case "test_started":
        addEvent(
          eventType,
          "Docker Sandbox Tests Started",
          `Executing: ${data.command}`,
          "info",
        );
        break;

      case "test_passed":
        setTestResult({
          success: true,
          exit_code: data.exit_code,
          command: data.command,
        });
        addEvent(
          eventType,
          "Verification Test Suite Passed",
          undefined,
          "success",
        );
        break;

      case "test_failed":
        setTestResult({
          success: false,
          exit_code: data.exit_code,
          command: data.command,
        });
        addEvent(
          eventType,
          "Verification Tests Failed",
          `Exit code: ${data.exit_code}`,
          "error",
        );
        break;

      case "repair_started":
        addEvent(
          eventType,
          `Repair Cycle #${data.repair_count} Initiated`,
          undefined,
          "warning",
        );
        break;

      case "review_started":
        setReviewResult({
          verdict: data.verdict || "approved",
          summary: "Review audit completed",
          issues: [],
          security_concerns: [],
          required_changes: [],
        });
        addEvent(
          eventType,
          "Code Review Audit Concluded",
          `Verdict: ${data.verdict}`,
          "info",
        );
        break;

      case "task_completed":
        setStatus("completed");
        setFinalResult({
          status: "completed",
          summary: data.summary,
          files_changed: [],
          tests: [],
        });
        setConnectionState("disconnected");
        addEvent(
          eventType,
          "Task Finished Successfully",
          data.summary,
          "success",
        );
        break;

      case "task_failed":
        setStatus("failed");
        setError(data.error || "Task execution failed.");
        setConnectionState("disconnected");
        addEvent(eventType, "Task Execution Failed", data.error, "error");
        break;
    }
  };

  // Form submission: Create task -> Trigger /run -> Connect /events
  const handleStartTask = async (wsPath: string, userPrompt: string) => {
    setIsLoading(true);
    setError(null);
    setEvents([]);
    setPendingPatch(null);
    setFinalResult(null);
    setTestResult(null);
    setReviewResult(null);

    try {
      // 1. Create task
      const created = await createTask(wsPath, userPrompt);
      setTaskId(created.id);
      setStatus("running");
      localStorage.setItem("irtrixai_active_task_id", created.id);

      addEvent(
        "task_created",
        `Task created: ${created.id.slice(0, 8)}`,
        undefined,
        "info",
      );

      // 2. Connect SSE for observation
      connectSSE(created.id);

      // 3. Trigger execution via POST /run
      const execRes = await runTask(created.id);
      setStatus(execRes.status.toLowerCase());

      if (execRes.status === "awaiting_approval") {
        setPendingPatch(execRes.interrupt_payload?.pending_patch || null);
        setCoderSummary(execRes.interrupt_payload?.coder_summary || null);
      }
    } catch (err: any) {
      console.error("Task initiation error:", err);
      setError(err.message || "Failed to start task.");
      setStatus("failed");
    } finally {
      setIsLoading(false);
    }
  };

  // HITL operator approval handler
  const handleApprove = async () => {
    if (!taskId || isSubmittingApproval) return;
    setIsSubmittingApproval(true);
    try {
      const res = await submitApproval(taskId, { approved: true });
      setStatus(res.status.toLowerCase());
      addEvent(
        "approval_submitted",
        "Changes Approved by Operator",
        undefined,
        "success",
      );

      if (res.status === "completed" && res.final_result) {
        setFinalResult(res.final_result);
      }
    } catch (err: any) {
      setError(err.message || "Approval submission failed.");
    } finally {
      setIsSubmittingApproval(false);
    }
  };

  // HITL operator rejection handler
  const handleReject = async (feedbackText: string) => {
    if (!taskId || isSubmittingApproval) return;
    setIsSubmittingApproval(true);
    try {
      const res = await submitApproval(taskId, {
        approved: false,
        feedback: feedbackText || "Rejected by operator",
      });
      setStatus(res.status.toLowerCase());
      addEvent(
        "approval_rejected",
        "Changes Rejected by Operator",
        feedbackText,
        "warning",
      );
    } catch (err: any) {
      setError(err.message || "Rejection submission failed.");
    } finally {
      setIsSubmittingApproval(false);
    }
  };

  const handleReset = () => {
    localStorage.removeItem("irtrixai_active_task_id");
    window.location.href = window.location.pathname;
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans">
      <Header
        taskId={taskId}
        status={status}
        connectionState={connectionState}
        onReset={handleReset}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Form, Controls, Approval Gate, Results */}
        <div className="lg:col-span-7 space-y-6">
          {!taskId ? (
            <TaskForm onSubmit={handleStartTask} isLoading={isLoading} />
          ) : (
            <>
              {status === "awaiting_approval" && (
                <ApprovalGate
                  coderSummary={coderSummary}
                  pendingPatch={pendingPatch}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  isSubmitting={isSubmittingApproval}
                />
              )}

              <TestResults testResult={testResult} />
              <ReviewOutcome review={reviewResult} />
              <FinalResult result={finalResult} error={error} />
            </>
          )}

          {error && status !== "completed" && !finalResult && (
            <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs">
              <span className="font-semibold">Error: </span>
              {error}
            </div>
          )}
        </div>

        {/* Right Column: Execution Timeline */}
        <div className="lg:col-span-5">
          <div className="sticky top-24">
            <Timeline events={events} />
          </div>
        </div>
      </main>
    </div>
  );
};

export default App;
