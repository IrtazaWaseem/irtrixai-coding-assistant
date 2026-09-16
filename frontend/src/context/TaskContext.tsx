import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  createTask,
  getTask,
  runTask,
  submitApproval,
  subscribeToEvents,
} from "../services/api";
import {
  ActivityEvent,
  FinalResult as FinalResultType,
  ReviewResult,
  TestResultData,
} from "../types";

export interface TaskContextType {
  taskId: string | null;
  status: string;
  events: ActivityEvent[];
  pendingPatch: string | null;
  coderSummary: string | null;
  testResult: TestResultData | null;
  reviewResult: ReviewResult | null;
  finalResult: FinalResultType | null;
  error: string | null;
  isLoading: boolean;
  isSubmittingApproval: boolean;
  connectionState: "connected" | "reconnecting" | "disconnected" | "idle";
  handleStartTask: (wsPath: string, userPrompt: string) => Promise<void>;
  handleApprove: () => Promise<void>;
  handleReject: (feedbackText: string) => Promise<void>;
  handleReset: () => void;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export const TaskProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
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

  const unsubscribeSseRef = useRef<(() => void) | null>(null);
  const seenEventKeysRef = useRef<Set<string>>(new Set());

  const cleanupSSE = useCallback(() => {
    if (unsubscribeSseRef.current) {
      unsubscribeSseRef.current();
      unsubscribeSseRef.current = null;
    }
  }, []);

  const addEvent = useCallback(
    (
      type: string,
      title: string,
      description?: string,
      statusType: "success" | "warning" | "error" | "info" = "info",
      metadata?: Record<string, any>,
      deterministicId?: string,
    ) => {
      const eventKey =
        deterministicId ||
        `${type}::${metadata?.repair_count ?? ""}::${metadata?.exit_code ?? ""}::${description || title}`;

      if (seenEventKeysRef.current.has(eventKey)) {
        return;
      }
      seenEventKeysRef.current.add(eventKey);

      const newEvent: ActivityEvent = {
        id: deterministicId || `${Date.now()}-${Math.random()}`,
        timestamp: new Date().toLocaleTimeString(),
        type,
        title,
        description,
        status: statusType,
        metadata,
      };
      setEvents((prev) => [...prev, newEvent]);
    },
    [],
  );

  const connectSSE = useCallback(
    (id: string) => {
      cleanupSSE();
      setConnectionState("connected");
      const unsubscribe = subscribeToEvents(
        id,
        (eventType: string, data: any, eventId?: string) => {
          handleServerEvent(eventType, data, eventId);
        },
        (err: Event) => {
          console.warn("SSE encountered a connection issue:", err);
          setConnectionState("reconnecting");
        },
      );

      unsubscribeSseRef.current = unsubscribe;
      return unsubscribe;
    },
    [cleanupSSE],
  );

  const handleServerEvent = (
    eventType: string,
    data: any,
    eventId?: string,
  ) => {
    switch (eventType) {
      case "task_started":
        setStatus("running");
        addEvent(
          eventType,
          "Agent Execution Started",
          undefined,
          "info",
          undefined,
          eventId,
        );
        break;

      case "task_not_started":
        setStatus("pending");
        addEvent(
          eventType,
          "Task Pending Run Command",
          data.message,
          "info",
          undefined,
          eventId,
        );
        break;

      case "workspace_inspected":
        addEvent(
          eventType,
          "Workspace Inspected",
          `Detected technologies: ${(data.tech_stack || []).join(", ")}`,
          "success",
          { tech_stack: data.tech_stack },
          eventId,
        );
        break;

      case "planning":
        addEvent(
          eventType,
          "Implementation Plan Formulated",
          data.plan_summary,
          "success",
          undefined,
          eventId,
        );
        break;

      case "coding":
        addEvent(
          eventType,
          "Code Modifications Proposed",
          `Target files: ${(data.files_changed || []).join(", ")}`,
          "info",
          undefined,
          eventId,
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
          undefined,
          eventId,
        );
        break;

      case "patch_applied":
        addEvent(
          eventType,
          "Approved Changes Applied to Workspace",
          undefined,
          "success",
          undefined,
          eventId,
        );
        break;

      case "test_started":
        addEvent(
          eventType,
          "Docker Sandbox Tests Started",
          `Executing: ${data.command}`,
          "info",
          undefined,
          eventId,
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
          { exit_code: data.exit_code },
          eventId,
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
          { exit_code: data.exit_code },
          eventId,
        );
        break;

      case "repair_started":
        addEvent(
          eventType,
          `Repair Cycle #${data.repair_count} Initiated`,
          undefined,
          "warning",
          { repair_count: data.repair_count },
          eventId,
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
          undefined,
          eventId,
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
        cleanupSSE();
        addEvent(
          eventType,
          "Task Finished Successfully",
          data.summary,
          "success",
          undefined,
          eventId,
        );
        break;

      case "task_failed":
        setStatus("failed");
        setError(data.error || "Task execution failed.");
        setConnectionState("disconnected");
        cleanupSSE();
        addEvent(
          eventType,
          "Task Execution Failed",
          data.error,
          "error",
          undefined,
          eventId,
        );
        break;
    }
  };

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

    return () => {
      cleanupSSE();
    };
  }, [connectSSE, addEvent, cleanupSSE]);

  const handleStartTask = async (wsPath: string, userPrompt: string) => {
    setIsLoading(true);
    setError(null);
    seenEventKeysRef.current.clear();
    setEvents([]);
    setPendingPatch(null);
    setFinalResult(null);
    setTestResult(null);
    setReviewResult(null);
    cleanupSSE();

    try {
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

      connectSSE(created.id);

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
      cleanupSSE();
    } finally {
      setIsLoading(false);
    }
  };

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
        cleanupSSE();
      }
    } catch (err: any) {
      setError(err.message || "Approval submission failed.");
    } finally {
      setIsSubmittingApproval(false);
    }
  };

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
      if (res.status === "aborted" || res.status === "failed") {
        cleanupSSE();
      }
    } catch (err: any) {
      setError(err.message || "Rejection submission failed.");
    } finally {
      setIsSubmittingApproval(false);
    }
  };

  const handleReset = () => {
    cleanupSSE();
    localStorage.removeItem("irtrixai_active_task_id");
    window.location.href = window.location.pathname;
  };

  return (
    <TaskContext.Provider
      value={{
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
        connectionState,
        handleStartTask,
        handleApprove,
        handleReject,
        handleReset,
      }}
    >
      {children}
    </TaskContext.Provider>
  );
};

export const useTaskExecution = (): TaskContextType => {
  const context = useContext(TaskContext);
  if (!context) {
    throw new Error("useTaskExecution must be used within a TaskProvider");
  }
  return context;
};
