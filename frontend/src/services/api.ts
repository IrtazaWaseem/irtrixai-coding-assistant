import { ApprovalRequest, ExecutionResponse, TaskResponse } from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public details?: any,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorMsg = `Request failed with status ${res.status}`;
    let details: any = null;
    try {
      const errJson = await res.json();
      errorMsg = errJson.message || errJson.detail || errorMsg;
      details = errJson;
    } catch {
      // Body was not JSON
    }
    throw new ApiError(res.status, errorMsg, details);
  }
  return res.json() as Promise<T>;
}

export async function createTask(
  workspacePath: string,
  prompt: string,
): Promise<TaskResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_path: workspacePath.trim(),
      prompt: prompt.trim(),
    }),
  });
  return handleResponse<TaskResponse>(res);
}

export async function getTask(taskId: string): Promise<TaskResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tasks/${taskId}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return handleResponse<TaskResponse>(res);
}

export async function runTask(taskId: string): Promise<ExecutionResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tasks/${taskId}/run`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return handleResponse<ExecutionResponse>(res);
}

export async function submitApproval(
  taskId: string,
  payload: ApprovalRequest,
): Promise<ExecutionResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tasks/${taskId}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<ExecutionResponse>(res);
}

export function subscribeToEvents(
  taskId: string,
  onEvent: (eventType: string, data: any) => void,
  onError: (err: Event) => void,
): () => void {
  const url = `${API_BASE}/api/v1/tasks/${taskId}/events`;
  const es = new EventSource(url);

  const eventNames = [
    "task_started",
    "task_not_started",
    "workspace_inspected",
    "planning",
    "coding",
    "approval_required",
    "patch_applied",
    "test_started",
    "test_passed",
    "test_failed",
    "repair_started",
    "review_started",
    "task_completed",
    "task_failed",
  ];

  eventNames.forEach((eventName) => {
    es.addEventListener(eventName, (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        onEvent(eventName, parsed);
      } catch (err) {
        console.warn(
          `Failed to parse SSE payload for event ${eventName}:`,
          err,
        );
      }
    });
  });

  es.onerror = (e) => {
    onError(e);
  };

  return () => {
    es.close();
  };
}
