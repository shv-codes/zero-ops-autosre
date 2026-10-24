// Mirrors the backend /api/v1 contract (backend/incidents/api).

export type IncidentStatus =
  | "ALERT_RECEIVED"
  | "MITIGATING"
  | "DIAGNOSING"
  | "CORRELATING"
  | "PATCHING"
  | "TESTING_IN_SANDBOX"
  | "PR_CREATED"
  | "UPDATING_PR"
  | "AWAITING_APPROVAL"
  | "READY_TO_MERGE"
  | "RESOLVED"
  | "ESCALATED"

export type RunMode = "cached" | "live" | "replay"

export type LogTag = "ALERT" | "MITIGATE" | "DIAG" | "CORR" | "PATCH" | "AGENT" | "GUARD" | "TEST" | "PR" | "LOOP"

export interface TimelineEntry {
  id: number
  ts: string
  tag: LogTag
  message: string
  state: IncidentStatus
}

export interface BranchReview {
  sha: string
  short_sha: string
  author: string
  message: string
  conflicts: boolean
  conflict_files: string[]
  sandbox: {
    passed: boolean
    engine: string
    duration_seconds: number
    output: string
    commands: string[]
  } | null
  repair_summary: string | null
}

export interface PullRequestInfo {
  number?: number
  url?: string
  state?: "open" | "closed" | "merged"
  draft?: boolean
  conflicts?: boolean
  provider?: "local" | "github"
  head_branch?: string
  base_branch?: string
  rounds?: number
  checks?: string
  title?: string
  reviews?: BranchReview[]
}

export interface SuspectInfo {
  commit?: { sha: string; short_sha: string; author: string; email: string; date: string; message: string }
  files?: string[]
  primary_file?: string
  location?: { file: string; function?: string; start_line?: number; end_line?: number; snippet?: string; blame_ratio?: number }
  confidence?: number
  score?: number
  evidence?: string[]
  candidates?: { sha: string; author: string; message: string; score: number }[]
}

export interface StuckGroup {
  application_name: string
  query: string
  example_query: string
  count: number
  max_idle_seconds: number
}

export interface Diagnosis {
  snapshot?: { total: number; max_connections: number; idle_in_transaction: number; active: number; idle: number }
  baseline?: Record<string, number> | null
  delta?: Record<string, number> | null
  stuck_sessions?: { count: number; groups: StuckGroup[] }
  findings?: string[]
  hypothesis?: string
  logs?: { errors?: Record<string, number>; readable?: boolean; note?: string }
}

export interface FixInfo {
  summary?: string
  risk?: "Low" | "Medium" | "High"
  risk_reason?: string
  attempts?: number
  steps?: number
  tests?: string[]
  files?: string[]
  brain?: { mode: string; provider: string; model: string; fallback_used: boolean; fallback_reason: string }
}

export interface PendingApproval {
  gate?: "mitigation" | "fix"
  title?: string
  details?: Record<string, unknown>
  requested_at?: string
  timeout_seconds?: number
  decision?: "approve" | "deny" | null
}

export interface AiCard {
  decision_maker: { mode: string; provider: string; model: string; fallback_used: boolean; fallback_reason: string }
  human_oversight: { approval_mode: string; decisions: { gate: string; approved: boolean; by: string }[]; merge: string }
  data_shared: { sent_to: string; evidence_sources: string[]; secrets_redacted: number; personal_data_redacted: number;
    injection_lines_neutralized: number; never_sent: string }
  verification: { sandbox_isolated: boolean; regression_test_fails_on_old_code: boolean | null; attempts: number | null }
  usage: { llm_calls: number; prompt_tokens: number; completion_tokens: number; agent_steps: number; elapsed_seconds: number }
  limitations: string[]
}

export interface RelatedIncident {
  id: string
  status: IncidentStatus
  created_at: string
  match: string
  pr_url: string | null
  fix_summary: string
}

export interface IncidentSummary {
  id: string
  status: IncidentStatus
  mode: RunMode
  approval_mode: "autonomous" | "review"
  pending_approval: PendingApproval
  source: string
  alert: Record<string, unknown>
  attempt: number
  max_attempts: number
  branch: string
  pull_request: PullRequestInfo
  sandbox_isolated: boolean | null
  escalation_reason: string
  created_at: string
  mitigated_at: string | null
  pr_opened_at: string | null
  ready_at: string | null
  finished_at: string | null
  mttr_seconds: number | null
  time_to_mitigate_seconds: number | null
}

export interface Incident extends IncidentSummary {
  telemetry: Record<string, unknown>
  mitigation: { terminated?: number; app_prefix?: string; error?: string; after?: { total: number; max_connections: number } }
  diagnosis: Diagnosis
  suspect: SuspectInfo
  project_profile: { language?: string; source?: string; test?: string; checks?: string[] }
  fix: FixInfo
  llm: { mode?: string; provider?: string; model?: string; fallback_used?: boolean; fallback_reason?: string }
  timeline: TimelineEntry[]
  related_incidents: RelatedIncident[]
  ai_card: AiCard | Record<string, never>
}

export interface AgentStep {
  id: number
  ts: string
  task: "fix" | "resolve_conflict" | "fix_ci"
  attempt: number
  step: number
  thought: string
  tool: string
  args: Record<string, unknown>
  ok: boolean
  result: string
}

export interface SandboxRun {
  id: number
  ts: string
  task: string
  attempt: number
  engine: string
  isolated: boolean
  passed: boolean
  reproduced: boolean | null
  exit_code: number
  timed_out: boolean
  duration_seconds: number
  output: string
  limits: Record<string, unknown>
}

export interface GuardrailCheck {
  id: string
  name: string
  status: "passed" | "failed" | "pending"
  passed: boolean | null
  details: string
  attempt?: number
}

export interface ConnectionTelemetry {
  active: number
  idle: number
  idle_in_transaction: number
  other: number
  total: number
  max: number
  utilization: number
  by_application: Record<string, number>
  live: boolean
}

export interface ConnectionHistoryPoint {
  timestamp: string
  active: number
  idle: number
  idle_in_transaction: number
  total: number
  max: number
}

export interface SystemStatus {
  mode: RunMode
  llm: { provider: string; model: string; configured: boolean }
  delivery: { provider: "local" | "github"; target: string; configured: boolean }
  sandbox: { engine: "docker" | "subprocess" | "cached"; isolated: boolean; setting: string }
  database: { reachable: boolean; error: string | null; engine: string; host: string }
  monitor: { running: boolean; last_error: string | null; threshold: number; enabled: boolean }
  victim: { base_url: string }
}

export interface SystemConfig {
  mode: RunMode
  max_attempts: number
  llm_provider: string
  alert_threshold: number
  monitor_enabled: boolean
  approval_mode: "autonomous" | "review"
}

export interface TrafficStatus {
  sent: number
  ok: number
  errors: number
  running: boolean
  target: number
}

export interface GitHubStatus {
  provider: "local" | "github"
  repo: string
  auth_mode: "app" | "token" | "none"
  connected: boolean
  installation_id: number | null
  account: string
  app: { mode: "app"; app_slug: string; app_name: string; bot_login: string; install_url: string } | null
  token_expires_in_seconds: number | null
  error: string | null
}

export interface ApiError {
  code: string
  message: string
}

export interface ApiResponse<T> {
  data: T
  error: ApiError | null
  meta: { timestamp: string }
}
