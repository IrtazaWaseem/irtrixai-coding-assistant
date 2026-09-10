export type TaskStatus =
  | "pending"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskResponse {
  id: string;
  workspace_path: string;
  prompt: string;
  thread_id: string;
  status: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRequest {
  approved: boolean;
  feedback?: string | null;
}

export interface InterruptPayload {
  action: string;
  pending_patch?: string | null;
  coder_summary?: string | null;
}

export interface ReviewResult {
  verdict: "approved" | "rejected" | "changes_requested";
  summary: string;
  issues: string[];
  security_concerns: string[];
  required_changes: string[];
}

export interface FinalResult {
  status: string;
  summary: string;
  files_changed: string[];
  tests: string[];
  review?: ReviewResult | null;
}

export interface ExecutionResponse {
  task_id: string;
  status: string;
  current_step?: number | null;
  next_step?: string | null;
  interrupt_payload?: InterruptPayload | null;
  final_result?: FinalResult | null;
  error?: string | null;
}

export interface ActivityEvent {
  id: string;
  timestamp: string;
  type: string;
  title: string;
  description?: string;
  step?: number;
  metadata?: Record<string, any>;
  status?: "success" | "warning" | "error" | "info";
}

export interface TestResultData {
  success: boolean;
  command?: string | string[];
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  output?: string;
}
