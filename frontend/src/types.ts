export interface TaskResponse {
  id: string;
  workspace_id?: string;
  prompt?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  interrupt_payload?: {
    pending_patch?: string;
    coder_summary?: string;
    [key: string]: any;
  };
  test_result?: any;
  final_result?: any;
  review_summary?: any;
}

export interface ExecutionResponse {
  task_id: string;
  status: string;
  node?: string;
  interrupt_payload?: any;
  final_result?: any;
}

export interface ApprovalRequest {
  approved: boolean;
  feedback?: string;
}

export interface ActivityEvent {
  id: string;
  timestamp: string;
  type: string;
  title: string;
  description?: string;
  status: "success" | "warning" | "error" | "info";
  metadata?: Record<string, any>;
}

export interface TestResultData {
  success: boolean;
  exit_code: number;
  command?: string;
  stdout?: string;
  stderr?: string;
  output?: string;
}

export interface ReviewResult {
  verdict: string;
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
}

// ==================== Phase 2A Additions ====================

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number;
  children?: FileNode[];
}

export interface WorkspaceResponse {
  id: string;
  name: string;
  root_path: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceTreeResponse {
  workspace_id: string;
  root_path: string;
  tree: FileNode[];
  total_entries: number;
}

export interface SystemStatusResponse {
  status: string;
  version: string;
  environment: string;
}

export interface LLMInfoResponse {
  provider: string;
  model: string;
  display_name: string;
  capabilities: {
    supports_streaming?: boolean;
    supports_structured_output?: boolean;
    supports_tools?: boolean;
    supports_system_messages?: boolean;
    [key: string]: any;
  };
  primary_provider?: string;
  models?: string[];
  fallback_provider?: string | null;
}
