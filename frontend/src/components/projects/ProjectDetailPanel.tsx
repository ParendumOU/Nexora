"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { projectsApi, agentsApi } from "@/lib/api";
import {
  X, FolderKanban, Bot, Wrench, Network, Key, CheckSquare,
  ScrollText, GitBranch, Calendar, Clock, Loader2, ChevronRight,
  Circle, CheckCircle2, AlertCircle, Pause, Play, Timer,
  CircleDot, ArrowUp, Minus, ArrowDown, AlertTriangle, RefreshCw,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

export type Project = {
  id: string;
  name: string;
  description: string | null;
  repo_url: string | null;
  repo_type: string | null;
  status: string;
  pm_agent_id: string | null;
  pm_agent_name: string | null;
  provider_chain_id: string | null;
  created_at: string;
  updated_at: string;
};

type Task = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  assigned_agent_name: string | null;
  checklist: { id: string; item: string; done: boolean }[];
  created_at: string;
  completed_at: string | null;
};

type LogEntry = {
  id: string;
  agent_name: string | null;
  level: string;
  message: string;
  created_at: string;
};

type AgentDetail = {
  id: string;
  name: string;
  agent_type: string;
  description: string | null;
  skills: string[];
  tools: string[];
  mcps: { name: string; url: string; allowed_tools?: string[] }[];
  env_vars: Record<string, string>;
};

type IssueEntry = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  labels: string[];
  assigned_agent_name: string | null;
  external_ref: string | null;
  created_at: string;
  closed_at: string | null;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview", label: "Overview", Icon: FolderKanban },
  { id: "agents", label: "Agents", Icon: Bot },
  { id: "resources", label: "Resources", Icon: Wrench },
  { id: "issues", label: "Issues", Icon: CircleDot },
  { id: "tasks", label: "Tasks", Icon: CheckSquare },
  { id: "logs", label: "Logs", Icon: ScrollText },
] as const;
type TabId = (typeof TABS)[number]["id"];

function fmtDate(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium", timeStyle: "short",
  });
}

function fmtRelative(iso: string) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const TASK_STATUS_CFG: Record<string, { label: string; Icon: React.ElementType; color: string }> = {
  running:   { label: "Running",   Icon: Play,         color: "text-cyan-400" },
  pending:   { label: "Pending",   Icon: Circle,       color: "text-yellow-400" },
  queued:    { label: "Queued",    Icon: Timer,        color: "text-blue-400" },
  paused:    { label: "Paused",    Icon: Pause,        color: "text-orange-400" },
  completed: { label: "Completed", Icon: CheckCircle2, color: "text-green-400" },
  failed:    { label: "Failed",    Icon: AlertCircle,  color: "text-red-400" },
};

const LOG_COLORS: Record<string, string> = {
  debug: "text-muted-foreground",
  info:  "text-foreground",
  warn:  "text-yellow-400",
  error: "text-red-400",
};

// ─── Tab content components ───────────────────────────────────────────────────

function OverviewTab({ project }: { project: Project }) {
  return (
    <div className="space-y-6">
      {/* Metadata */}
      <div className="space-y-1">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Project Info
        </p>
        <PropertyRow label="Status">
          <Badge variant="secondary" className={cn(
            "text-[10px] h-4 px-1.5",
            project.status === "active" ? "text-green-400" : "text-muted-foreground"
          )}>
            {project.status}
          </Badge>
        </PropertyRow>
        <PropertyRow label="Created"><span className="text-xs">{fmtDate(project.created_at)}</span></PropertyRow>
        <PropertyRow label="Updated"><span className="text-xs">{fmtDate(project.updated_at)}</span></PropertyRow>
        {project.repo_url && (
          <PropertyRow label="Repository">
            <a href={project.repo_url} target="_blank" rel="noopener noreferrer"
              className="text-xs text-primary hover:underline flex items-center gap-1">
              <GitBranch className="w-3 h-3" />
              {project.repo_url.replace("https://", "")}
            </a>
          </PropertyRow>
        )}
        {project.pm_agent_name && (
          <PropertyRow label="PM Agent">
            <span className="text-xs flex items-center gap-1">
              <Bot className="w-3 h-3 text-primary" />
              {project.pm_agent_name}
            </span>
          </PropertyRow>
        )}
      </div>

      {project.description && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
            Description
          </p>
          <p className="text-sm text-muted-foreground">{project.description}</p>
        </div>
      )}
    </div>
  );
}

function PropertyRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div>{children}</div>
    </div>
  );
}

function AgentsTab({ project }: { project: Project }) {
  const { data: agent, isLoading } = useQuery<AgentDetail>({
    queryKey: ["agent", project.pm_agent_id],
    queryFn: () => agentsApi.get(project.pm_agent_id!).then((r) => r.data),
    enabled: !!project.pm_agent_id,
  });

  if (!project.pm_agent_id) {
    return <EmptyState icon={Bot} text="No agents assigned to this project" />;
  }
  if (isLoading) return <Loading />;

  return (
    <div className="space-y-4">
      {agent && (
        <div className="border border-border rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <Bot className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium">{agent.name}</p>
              <p className="text-xs text-muted-foreground">{agent.agent_type}</p>
            </div>
            <Badge variant="secondary" className="ml-auto text-[10px] h-4 px-1.5">PM</Badge>
          </div>
          {agent.description && (
            <p className="text-xs text-muted-foreground">{agent.description}</p>
          )}
          {agent.skills.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.skills.map((s) => (
                <span key={s} className="text-[10px] px-1.5 py-0.5 bg-accent rounded font-mono">
                  {s}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResourcesTab({ project }: { project: Project }) {
  const { data: agent, isLoading } = useQuery<AgentDetail>({
    queryKey: ["agent", project.pm_agent_id],
    queryFn: () => agentsApi.get(project.pm_agent_id!).then((r) => r.data),
    enabled: !!project.pm_agent_id,
  });

  if (!project.pm_agent_id) {
    return <EmptyState icon={Wrench} text="No PM agent — no resources configured" />;
  }
  if (isLoading) return <Loading />;

  const tools = agent?.tools ?? [];
  const mcps = agent?.mcps ?? [];
  const envEntries = Object.entries(agent?.env_vars ?? {});

  return (
    <div className="space-y-6">
      {/* Tools */}
      <ResourceSection icon={Wrench} title="Tools" count={tools.length}>
        {tools.length === 0
          ? <p className="text-xs text-muted-foreground">No tools configured</p>
          : <div className="flex flex-wrap gap-1.5">
              {tools.map((t) => (
                <span key={t} className="text-xs px-2 py-0.5 bg-accent rounded font-mono">{t}</span>
              ))}
            </div>
        }
      </ResourceSection>

      {/* MCP Servers */}
      <ResourceSection icon={Network} title="MCP Servers" count={mcps.length}>
        {mcps.length === 0
          ? <p className="text-xs text-muted-foreground">No MCP servers configured</p>
          : <div className="space-y-2">
              {mcps.map((m, i) => (
                <div key={i} className="flex items-start gap-2 p-2 bg-accent/30 rounded-lg">
                  <Network className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{m.name}</p>
                    <p className="text-[10px] text-muted-foreground font-mono truncate">{m.url}</p>
                    {m.allowed_tools && m.allowed_tools.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {m.allowed_tools.map((t) => (
                          <span key={t} className="text-[9px] px-1 py-0.5 bg-accent rounded font-mono">{t}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
        }
      </ResourceSection>

      {/* Environment Variables */}
      <ResourceSection icon={Key} title="Environment Variables" count={envEntries.length}>
        {envEntries.length === 0
          ? <p className="text-xs text-muted-foreground">No environment variables</p>
          : <div className="space-y-1">
              {envEntries.map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 font-mono text-xs">
                  <span className="text-muted-foreground shrink-0">{k}</span>
                  <span className="text-foreground/40">=</span>
                  <span className="text-foreground truncate">{v ? "••••••" : <span className="italic text-muted-foreground">empty</span>}</span>
                </div>
              ))}
            </div>
        }
      </ResourceSection>
    </div>
  );
}

function ResourceSection({
  icon: Icon, title, count, children,
}: {
  icon: React.ElementType;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{title}</span>
        <span className="text-xs text-muted-foreground ml-auto">{count}</span>
      </div>
      {children}
    </div>
  );
}

function TasksTab({ project }: { project: Project }) {
  const { data: tasks = [], isLoading } = useQuery<Task[]>({
    queryKey: ["project-tasks", project.id],
    queryFn: () => projectsApi.tasks(project.id).then((r) => r.data),
  });

  if (isLoading) return <Loading />;
  if (tasks.length === 0) return <EmptyState icon={CheckSquare} text="No tasks yet" />;

  const ORDER: (keyof typeof TASK_STATUS_CFG)[] = ["running", "pending", "queued", "paused", "completed", "failed"];
  const grouped = ORDER.reduce<Record<string, Task[]>>((acc, s) => {
    acc[s] = tasks.filter((t) => t.status === s);
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      {ORDER.map((status) => {
        const list = grouped[status];
        if (list.length === 0) return null;
        const cfg = TASK_STATUS_CFG[status];
        const Icon = cfg.Icon;
        return (
          <div key={status}>
            <div className="flex items-center gap-2 mb-2">
              <Icon className={cn("w-3.5 h-3.5", cfg.color)} />
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{cfg.label}</span>
              <span className="text-xs text-muted-foreground ml-auto">{list.length}</span>
            </div>
            <div className="space-y-1.5">
              {list.map((task) => (
                <div key={task.id} className="p-3 border border-border/60 rounded-lg space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-medium leading-snug">{task.title}</p>
                    {task.assigned_agent_name && (
                      <span className="text-[10px] text-muted-foreground shrink-0 flex items-center gap-1">
                        <Bot className="w-3 h-3" />{task.assigned_agent_name}
                      </span>
                    )}
                  </div>
                  {task.description && (
                    <p className="text-[11px] text-muted-foreground line-clamp-2">{task.description}</p>
                  )}
                  {task.checklist.length > 0 && (
                    <div className="text-[10px] text-muted-foreground">
                      {task.checklist.filter((c) => c.done).length}/{task.checklist.length} checklist items
                    </div>
                  )}
                  <p className="text-[10px] text-muted-foreground">
                    {task.completed_at ? `Completed ${fmtRelative(task.completed_at)}` : fmtRelative(task.created_at)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function LogsTab({ project }: { project: Project }) {
  const { data: logs = [], isLoading } = useQuery<LogEntry[]>({
    queryKey: ["project-logs", project.id],
    queryFn: () => projectsApi.logs(project.id).then((r) => r.data),
    refetchInterval: 10000,
  });

  if (isLoading) return <Loading />;
  if (logs.length === 0) return <EmptyState icon={ScrollText} text="No logs yet" />;

  return (
    <div className="bg-neutral-950 rounded-lg p-3 font-mono text-xs space-y-0.5">
      {logs.map((log) => (
        <div key={log.id} className="flex gap-2">
          <span className="text-muted-foreground/40 shrink-0 select-none">
            {new Date(log.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
          {log.agent_name && (
            <span className="text-blue-300 shrink-0">[{log.agent_name}]</span>
          )}
          <span className={LOG_COLORS[log.level] ?? "text-foreground"}>{log.message}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Shared micro-components ─────────────────────────────────────────────────

function Loading() {
  return (
    <div className="flex items-center justify-center h-32 text-muted-foreground">
      <Loader2 className="w-5 h-5 animate-spin" />
    </div>
  );
}

function EmptyState({ icon: Icon, text }: { icon: React.ElementType; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground">
      <Icon className="w-8 h-8 opacity-20" />
      <p className="text-sm">{text}</p>
    </div>
  );
}

// ─── Issue helpers ────────────────────────────────────────────────────────────

const ISSUE_STATUS_CFG: Record<string, { label: string; Icon: React.ElementType; color: string }> = {
  open:        { label: "Open",        Icon: CircleDot,    color: "text-green-400" },
  in_progress: { label: "In Progress", Icon: Play,         color: "text-blue-400" },
  review:      { label: "Review",      Icon: Timer,        color: "text-amber-400" },
  closed:      { label: "Closed",      Icon: CheckCircle2, color: "text-muted-foreground" },
};

const PRIORITY_ICON: Record<string, { Icon: React.ElementType; color: string }> = {
  critical: { Icon: AlertTriangle, color: "text-red-400" },
  high:     { Icon: ArrowUp,       color: "text-orange-400" },
  medium:   { Icon: Minus,         color: "text-yellow-400" },
  low:      { Icon: ArrowDown,     color: "text-muted-foreground" },
};

function IssuesTab({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const { data: issues = [], isLoading } = useQuery<IssueEntry[]>({
    queryKey: ["project-issues", project.id],
    queryFn: () => projectsApi.issues(project.id).then((r) => r.data),
    refetchInterval: 10000,
  });

  const syncMutation = useMutation({
    mutationFn: () => projectsApi.syncIssues(project.id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["project-issues", project.id] });
    },
  });

  if (isLoading) return <Loading />;

  return (
    <div className="space-y-5">
      {/* Sync header */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {issues.length} issue{issues.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-md border border-border/60 hover:bg-accent/50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-3 h-3", syncMutation.isPending && "animate-spin")} />
          {syncMutation.isPending ? "Syncing…" : "Sync from Git"}
        </button>
      </div>

      {syncMutation.isSuccess && syncMutation.data?.data && (
        <div className="text-[11px] text-green-400 bg-green-400/10 px-3 py-1.5 rounded-md">
          Imported {syncMutation.data.data.imported} issue{syncMutation.data.data.imported !== 1 ? "s" : ""},
          {" "}{syncMutation.data.data.skipped} already synced
        </div>
      )}

      {syncMutation.isError && (
        <div className="text-[11px] text-red-400 bg-red-400/10 px-3 py-1.5 rounded-md">
          Sync failed: {(syncMutation.error as Error)?.message || "Unknown error"}
        </div>
      )}

      {issues.length === 0 ? (
        <EmptyState icon={CircleDot} text="No issues yet — sync from Git or create one" />
      ) : (
        <>
          {(() => {
            const ORDER = ["open", "in_progress", "review", "closed"];
            const grouped = ORDER.reduce<Record<string, IssueEntry[]>>((acc, s) => {
              acc[s] = issues.filter((i) => i.status === s);
              return acc;
            }, {});
            return ORDER.map((status) => {
              const list = grouped[status];
              if (!list || list.length === 0) return null;
              const cfg = ISSUE_STATUS_CFG[status] ?? ISSUE_STATUS_CFG.open;
              const StatusIcon = cfg.Icon;
              return (
                <div key={status}>
                  <div className="flex items-center gap-2 mb-2">
                    <StatusIcon className={cn("w-3.5 h-3.5", cfg.color)} />
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{cfg.label}</span>
                    <span className="text-xs text-muted-foreground ml-auto">{list.length}</span>
                  </div>
                  <div className="space-y-1.5">
                    {list.map((issue) => {
                      const pri = PRIORITY_ICON[issue.priority] ?? PRIORITY_ICON.medium;
                      const PriIcon = pri.Icon;
                      return (
                        <div key={issue.id} className="p-3 border border-border/60 rounded-lg space-y-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-1.5">
                              <PriIcon className={cn("w-3 h-3 shrink-0", pri.color)} />
                              <p className="text-xs font-medium leading-snug">{issue.title}</p>
                              {issue.external_ref && (
                                <Badge variant="outline" className="text-[9px] h-3.5 px-1 font-mono">{issue.external_ref}</Badge>
                              )}
                            </div>
                            {issue.assigned_agent_name && (
                              <span className="text-[10px] text-muted-foreground shrink-0 flex items-center gap-1">
                                <Bot className="w-3 h-3" />{issue.assigned_agent_name}
                              </span>
                            )}
                          </div>
                          {issue.description && (
                            <p className="text-[11px] text-muted-foreground line-clamp-2">{issue.description}</p>
                          )}
                          {issue.labels.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {issue.labels.slice(0, 4).map(l => (
                                <span key={l} className="text-[9px] px-1.5 py-0.5 bg-accent/60 rounded font-mono">{l}</span>
                              ))}
                            </div>
                          )}
                          <p className="text-[10px] text-muted-foreground">
                            {issue.closed_at ? `Closed ${fmtRelative(issue.closed_at)}` : fmtRelative(issue.created_at)}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            });
          })()}
        </>
      )}
    </div>
  );
}

// ─── Panel ───────────────────────────────────────────────────────────────────

export function ProjectDetailPanel({
  project,
  onClose,
  defaultTab = "overview",
}: {
  project: Project;
  onClose: () => void;
  defaultTab?: TabId;
}) {
  const [activeTab, setActiveTab] = useState<TabId>(defaultTab);

  return (
    <div className="fixed inset-0 z-50 flex items-stretch">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="w-[780px] bg-card border-l border-border flex flex-col shadow-2xl">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border flex items-center gap-4 shrink-0">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <FolderKanban className="w-5 h-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold truncate">{project.name}</h2>
            {project.description && (
              <p className="text-xs text-muted-foreground truncate">{project.description}</p>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {fmtRelative(project.created_at)}
            </span>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-accent transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-border px-6 flex gap-1 shrink-0">
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors",
                activeTab === id
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {activeTab === "overview" && <OverviewTab project={project} />}
          {activeTab === "agents" && <AgentsTab project={project} />}
          {activeTab === "resources" && <ResourcesTab project={project} />}
          {activeTab === "issues" && <IssuesTab project={project} />}
          {activeTab === "tasks" && <TasksTab project={project} />}
          {activeTab === "logs" && <LogsTab project={project} />}
        </div>
      </div>
    </div>
  );
}
