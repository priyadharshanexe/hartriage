export type Role = "admin" | "agent" | "viewer";
export type Severity = "critical" | "high" | "medium" | "info";

export interface OrgSummary {
  id: string;
  name: string;
  role: Role;
}

export interface Session {
  user: { id: string; email: string; name: string };
  org_id: string;
  role: Role | null;
  orgs: OrgSummary[];
  access_token?: string;
  expires_in?: number;
}

export interface Redaction {
  secrets?: Record<string, number>;
  occurrences?: Record<string, number>;
  total_secrets?: number;
  entries_touched?: number;
  response_bodies_removed?: number;
  request_bodies_removed?: number;
  websocket_messages_removed?: number;
  error_bodies_kept?: number;
  sentence?: string;
}

export interface Summary {
  activity: string[];
  first_failure: string;
  likely_cause: string;
  evidence: string[];
  next_step: string;
  kb_title: string;
  kb_url: string;
  redaction: string;
  other_findings: string[];
  notes: string[];
  lead_rule: string;
  engine_version: string;
}

export interface Source {
  kind: "upload" | "cli" | "ticket";
  platform?: "zendesk" | "freshdesk";
  ticket_id?: string;
  ticket_url?: string;
}

export interface Stats {
  entries: number;
  failed: number;
  hosts: Record<string, number>;
  host_count: number;
  statuses: Record<string, number>;
  first_started: string | null;
  last_finished: string | null;
  duration_seconds: number | null;
  bytes_received: number;
  truncated?: boolean;
  findings?: number;
}

export interface Analysis {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  engine_version: string | null;
  created_at: string;
  finished_at: string | null;
  filename: string | null;
  size_bytes: number;
  original_size_bytes: number;
  entry_count: number;
  expires_at: string;
  source: Source;
  redaction: Redaction;
  stats: Stats | null;
  lead: string | null;
  summary?: Summary | null;
  summary_md?: string | null;
}

export interface Finding {
  id: string;
  rule_id: string;
  severity: Severity;
  title: string;
  cause: string;
  next_step: string;
  confidence: "certain" | "likely";
  kb: string;
  entry: number | null;
  entries: number[];
  evidence: Record<string, unknown>;
  evidence_lines?: string[];
}

export type Phase = "blocked" | "dns" | "connect" | "ssl" | "send" | "wait" | "receive";

export interface EntryRow {
  number: number;
  started_ms: number | null;
  method: string;
  url: string;
  host: string;
  status: number;
  error: string;
  mime: string;
  resource_type: string;
  time_ms: number;
  timings: Partial<Record<Phase, number | null>>;
  request_bytes: number;
  response_bytes: number;
  failed: boolean;
}

export interface EntriesPage {
  items: EntryRow[];
  next_cursor: number | null;
  hosts: { host: string; count: number }[];
}

export interface NameValue {
  name: string;
  value: string;
}

export interface HarEntry {
  startedDateTime?: string;
  time?: number;
  serverIPAddress?: string;
  request: {
    method: string;
    url: string;
    httpVersion?: string;
    headers?: NameValue[];
    queryString?: NameValue[];
    cookies?: (NameValue & Record<string, unknown>)[];
    postData?: { mimeType?: string; text?: string; params?: NameValue[]; comment?: string };
    bodySize?: number;
  };
  response: {
    status: number;
    statusText?: string;
    httpVersion?: string;
    headers?: NameValue[];
    cookies?: (NameValue & Record<string, unknown>)[];
    content?: { size?: number; mimeType?: string; text?: string; comment?: string };
    redirectURL?: string;
  };
  timings?: Partial<Record<Phase, number>>;
  [key: string]: unknown;
}

export interface EntryMeta {
  credentials?: string[];
  credentials_present?: boolean;
  jwts?: { location: string; marker: string; exp: number | null; iat: number | null; nbf: number | null; aud: string[] }[];
  correlation_ids?: Record<string, string>;
  request_header_bytes?: number;
  cookie_header_bytes?: number;
}

export interface EntryDetail {
  number: number;
  entry: HarEntry;
  meta: EntryMeta;
}

export interface Connection {
  id: string;
  platform: "zendesk" | "freshdesk";
  subdomain: string;
  auth_type: string;
  replace_attachments: boolean;
  webhook_url: string;
  setup_steps: string[];
  last_webhook_at: string | null;
  last_webhook_status: string | null;
  created_at: string;
  secret_header: string | null;
  webhook_secret?: string;
  account?: string | null;
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  joined_at: string;
  you: boolean;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  invite_url?: string;
}

export interface AuditEntry {
  at: string;
  actor: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
}

export interface KbItem {
  slug: string;
  rule_id: string | null;
  title: string;
  summary: string;
}
