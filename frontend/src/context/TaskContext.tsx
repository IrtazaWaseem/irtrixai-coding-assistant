import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  cancelTask,
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
  TokenUsage,
} from "../types";

export interface TaskContextType {
  taskId: string | null;
  activeWorkspaceId: string | null;
  setActiveWorkspaceId: (id: string | null) => void;
  status: string;
  events: ActivityEvent[];
  pendingPatch: string | null;
  coderSummary: string | null;
  testResult: TestResultData | null;
  reviewResult: ReviewResult | null;
  finalResult: FinalResultType | null;
  tokenUsage: TokenUsage | null;
  reviewStatus: string | null;
  reviewAdvisory: string | null;
  error: string | null;
  isLoading: boolean;
  isSubmittingApproval: boolean;
  isCancelling: boolean;
  connectionState: "connected" | "reconnecting" | "disconnected" | "idle";
  handleStartTask: (
    wsPathOrId: string,
    userPrompt: string,
    provider?: string,
    model?: string,
  ) => Promise<void>;
  handleApprove: () => Promise<void>;
  handleReject: (feedbackText: string) => Promise<void>;
  handleReset: () => Promise<void>;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

const isTerminalStatus = (st: string): boolean => {
  const s = st.toLowerCase();
  return (
    s === "completed" || s === "failed" || s === "cancelled" || s === "aborted"
  );
};

export const TaskProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(
    null,
  );
  const [status, setStatus] = useState<string>("idle");
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [pendingPatch, setPendingPatch] = useState<string | null>(null);
  const [coderSummary, setCoderSummary] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResultData | null>(null);
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null);
  const [finalResult, setFinalResult] = useState<FinalResultType | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null);
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);
  const [reviewAdvisory, setReviewAdvisory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSubmittingApproval, setIsSubmittingApproval] =
    useState<boolean>(false);
  const [isCancelling, setIsCancelling] = useState<boolean>(false);
  const [connectionState, setConnectionState] = useState<
    "connected" | "reconnecting" | "disconnected" | "idle"
  >("idle");

  const unsubscribeSseRef = useRef<(() => void) | null>(null);
  const activeSseTaskIdRef = useRef<string | null>(null);
  const seenEventKeysRef = useRef<Set<string>>(new Set());

  const cleanupSSE = useCallback(() => {
    activeSseTaskIdRef.current = null;
    if (unsubscribeSseRef.current) {
      unsubscribeSseRef.current();
      unsubscribeSseRef.current = null;
    }
    setConnectionState("idle");
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
      activeSseTaskIdRef.current = id;
      setConnectionState("connected");
      const unsubscribe = subscribeToEvents(
        id,
        (eventType: string, data: any, eventId?: string) => {
          if (activeSseTaskIdRef.current !== id) {
            return; // Stale event discarded
          }
          handleServerEvent(eventType, data, eventId);
        },
        (err: Event) => {
          if (activeSseTaskIdRef.current !== id) {
            return;
          }
          console.warn("SSE encountered a connection issue:", err);
          setConnectionState("reconnecting");
        },
      );

      unsubscribeSseRef.current = () => {
        if (activeSseTaskIdRef.current === id) {
          activeSseTaskIdRef.current = null;
        }
        unsubscribe();
      };
      return unsubscribeSseRef.current;
    },
    [cleanupSSE],
  );

  const handleServerEvent = (
    eventType: string,
    data: any,
    eventId?: string,
  ) => {
    if (data.token_usage) {
      setTokenUsage(data.token_usage);
    }

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
        setReviewStatus("completed");
        setReviewAdvisory(null);
        addEvent(
          eventType,
          "Code Review Audit Concluded",
          `Verdict: ${data.verdict}`,
          "info",
          undefined,
          eventId,
        );
        break;

      case "review_skipped":
        setReviewStatus(data.review_status);
        setReviewAdvisory(data.advisory);
        addEvent(
          eventType,
          "Code Review Skipped (Advisory)",
          data.advisory || "Review step was skipped; automated tests passed.",
          "warning",
          { review_status: data.review_status, advisory: data.advisory },
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

      case "task_cancelled":
        setStatus("cancelled");
        setConnectionState("disconnected");
        cleanupSSE();
        addEvent(
          eventType,
          "Task Cancelled",
          data.summary || "Task was cancelled by operator.",
          "warning",
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
          if (t.workspace_id) {
            setActiveWorkspaceId(t.workspace_id);
          }
          if (t.token_usage) {
            setTokenUsage(t.token_usage);
          }
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

  const handleStartTask = async (
    wsPathOrId: string,
    userPrompt: string,
    provider?: string,
    model?: string,
  ) => {
    setIsLoading(true);
    setError(null);
    seenEventKeysRef.current.clear();
    setEvents([]);
    setPendingPatch(null);
    setFinalResult(null);
    setTestResult(null);
    setReviewResult(null);
    setTokenUsage(null);
    setReviewStatus(null);
    setReviewAdvisory(null);
    cleanupSSE();

    try {
      const created = await createTask(wsPathOrId, userPrompt, provider, model);
      setTaskId(created.id);
      if (created.workspace_id) {
        setActiveWorkspaceId(created.workspace_id);
      } else if (
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          wsPathOrId,
        )
      ) {
        setActiveWorkspaceId(wsPathOrId);
      }

      setStatus("running");
      localStorage.setItem("irtrixai_active_task_id", created.id);

      addEvent(
        "task_created",
        `Task created: ${created.id.slice(0, 8)} (${created.provider || "default"} / ${created.model || "default"})`,
        undefined,
        "info",
      );

      connectSSE(created.id);

      const execRes = await runTask(created.id);
      setStatus(execRes.status.toLowerCase());
      if (execRes.token_usage) {
        setTokenUsage(execRes.token_usage);
      }

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
      if (res.token_usage) {
        setTokenUsage(res.token_usage);
      }

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
      if (res.token_usage) {
        setTokenUsage(res.token_usage);
      }

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

  const handleReset = async () => {
    if (isCancelling) return;

    // If an active non-terminal task exists, cancel it first on the backend
    if (taskId && !isTerminalStatus(status)) {
      setIsCancelling(true);
      try {
        await cancelTask(taskId);
      } catch (err: any) {
        console.error("Task cancellation error:", err);
        setError(err.message || "Failed to cancel active task.");
        setIsCancelling(false);
        return; // Preserve active state so the user remains aware of backend state
      } finally {
        setIsCancelling(false);
      }
    }

    // After cancellation succeeds or if task was already terminal, clear local state cleanly
    cleanupSSE();
    localStorage.removeItem("irtrixai_active_task_id");

    if (window.location.search.includes("taskId")) {
      const url = new URL(window.location.href);
      url.searchParams.delete("taskId");
      window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    }

    setTaskId(null);
    setActiveWorkspaceId(null);
    setStatus("idle");
    setEvents([]);
    setPendingPatch(null);
    setCoderSummary(null);
    setTestResult(null);
    setReviewResult(null);
    setFinalResult(null);
    setTokenUsage(null);
    setReviewStatus(null);
    setReviewAdvisory(null);
    setError(null);
    setConnectionState("idle");
    seenEventKeysRef.current.clear();
  };

  return (
    <TaskContext.Provider
      value={{
        taskId,
        activeWorkspaceId,
        setActiveWorkspaceId,
        status,
        events,
        pendingPatch,
        coderSummary,
        testResult,
        reviewResult,
        finalResult,
        tokenUsage,
        reviewStatus,
        reviewAdvisory,
        error,
        isLoading,
        isSubmittingApproval,
        isCancelling,
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
