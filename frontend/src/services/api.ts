import {
  ApprovalRequest,
  ExecutionResponse,
  LLMInfoResponse,
  SystemStatusResponse,
  TaskResponse,
  WorkspaceResponse,
  WorkspaceTreeResponse,
} from "../types";

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

// ==================== Task API ====================

export async function createTask(
  workspaceIdOrPath: string,
  prompt: string,
): Promise<TaskResponse> {
  const isUuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      workspaceIdOrPath,
    );

  const payload = isUuid
    ? { workspace_id: workspaceIdOrPath, prompt }
    : { workspace_path: workspaceIdOrPath, prompt };

  const res = await fetch(`${API_BASE}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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
  onEvent: (eventType: string, data: any, eventId?: string) => void,
  onError: (err: Event) => void,
): () => void {
  const url = `${API_BASE}/api/v1/tasks/${taskId}/events`;
  const es = new EventSource(url);
  let isClosed = false;

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
      if (isClosed) return;
      try {
        const parsed = JSON.parse(e.data);
        const eventId = e.lastEventId || parsed?.id;
        onEvent(eventName, parsed, eventId);
      } catch (err) {
        console.warn(
          `Failed to parse SSE payload for event ${eventName}:`,
          err,
        );
      }
    });
  });

  es.onerror = (e) => {
    if (!isClosed) {
      onError(e);
    }
  };

  return () => {
    if (!isClosed) {
      isClosed = true;
      es.close();
    }
  };
}

// ==================== Workspace & System API ====================

export async function getWorkspaces(): Promise<WorkspaceResponse[]> {
  const res = await fetch(`${API_BASE}/api/v1/workspaces`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return handleResponse<WorkspaceResponse[]>(res);
}

export async function createWorkspace(
  name: string,
  rootPath: string,
): Promise<WorkspaceResponse> {
  const res = await fetch(`${API_BASE}/api/v1/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: name.trim(),
      root_path: rootPath.trim(),
    }),
  });
  return handleResponse<WorkspaceResponse>(res);
}

export async function getWorkspace(
  workspaceId: string,
): Promise<WorkspaceResponse> {
  const res = await fetch(`${API_BASE}/api/v1/workspaces/${workspaceId}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return handleResponse<WorkspaceResponse>(res);
}

export async function getWorkspaceTree(
  workspaceId: string,
  maxDepth: number = 3,
): Promise<WorkspaceTreeResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/workspaces/${workspaceId}/tree?max_depth=${maxDepth}`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  );
  return handleResponse<WorkspaceTreeResponse>(res);
}

export async function getSystemStatus(): Promise<SystemStatusResponse> {
  const res = await fetch(`${API_BASE}/api/v1/status`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return handleResponse<SystemStatusResponse>(res);
}

export async function getLLMInfo(): Promise<LLMInfoResponse> {
  const res = await fetch(`${API_BASE}/api/v1/llm/info`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return handleResponse<LLMInfoResponse>(res);
}
