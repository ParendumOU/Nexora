"use client";
import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { issuesApi, projectsApi, agentsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  CircleDot, Plus, Loader2, Search, X, Bot,
  FolderKanban, AlertTriangle, ArrowUp, Minus, ArrowDown,
  MessageSquare, ExternalLink, ChevronDown, Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, PageLoading, PageEmpty,
} from "@/components/layout/page-shell";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Issue {
  id: string;
  project_id: string;
  project_name: string | null;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  labels: string[];
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  reporter_user_name: string | null;
  reporter_agent_name: string | null;
  comment_count: number;
  external_ref: string | null;
  created_at: string;
  closed_at: string | null;
}

interface Project { id: string; name: string; }
interface Agent { id: string; name: string; }

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  open:        { label: "Open",        color: "text-green-400 bg-green-500/10 border-green-500/20",   dot: "bg-green-400" },
  in_progress: { label: "In Progress", color: "text-blue-400 bg-blue-500/10 border-blue-500/20",     dot: "bg-blue-400 animate-pulse" },
  review:      { label: "Review",      color: "text-amber-400 bg-amber-500/10 border-amber-500/20",  dot: "bg-amber-400" },
  closed:      { label: "Closed",      color: "text-muted-foreground bg-muted/30 border-border",     dot: "bg-muted-foreground" },
};

const PRIORITY_META: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  critical: { label: "Critical", icon: AlertTriangle, color: "text-red-400" },
  high:     { label: "High",     icon: ArrowUp,       color: "text-orange-400" },
  medium:   { label: "Medium",   icon: Minus,         color: "text-yellow-400" },
  low:      { label: "Low",      icon: ArrowDown,     color: "text-muted-foreground" },
};

function fmtRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ─── Create Issue Dialog ──────────────────────────────────────────────────────

function CreateIssueDialog({
  open, onClose, projects, agents,
}: {
  open: boolean; onClose: () => void; projects: Project[]; agents: Agent[];
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState(projects[0]?.id ?? "");
  const [priority, setPriority] = useState("medium");
  const [agentId, setAgentId] = useState("");
  const [labelsText, setLabelsText] = useState("");

  const create = useMutation({
    mutationFn: () =>
      issuesApi.create({
        project_id: projectId,
        title,
        description: description || undefined,
        priority,
        labels: labelsText ? labelsText.split(",").map(s => s.trim()).filter(Boolean) : [],
        assigned_agent_id: agentId || undefined,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["issues"] });
      toast.success("Issue created");
      onClose();
      router.push(`/issues/${res.data.id}`);
    },
    onError: () => toast.error("Failed to create issue"),
  });

  const canSubmit = title.trim() && projectId;

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">New Issue</Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">Track a problem, feature, or task</p>
          </div>

          <div className="p-5 space-y-3 max-h-[70vh] overflow-y-auto">
            {/* Title */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Title <span className="text-primary">*</span></label>
              <Input autoFocus value={title} onChange={e => setTitle(e.target.value)} className="h-8 text-sm" placeholder="Brief description of the issue" />
            </div>

            {/* Description */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Description <span className="opacity-50">(markdown)</span></label>
              <textarea
                value={description} onChange={e => setDescription(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="Detailed description, steps to reproduce, expected behavior..."
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Project */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Project <span className="text-primary">*</span></label>
                <Select.Root value={projectId} onValueChange={setProjectId}>
                  <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-xs focus:outline-none">
                    <Select.Value placeholder="Select project…" /><ChevronDown className="w-3 h-3 opacity-50" />
                  </Select.Trigger>
                  <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
                    {projects.map(p => (
                      <Select.Item key={p.id} value={p.id} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                        <Select.ItemText>{p.name}</Select.ItemText>
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </div>

              {/* Priority */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Priority</label>
                <Select.Root value={priority} onValueChange={setPriority}>
                  <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-xs focus:outline-none">
                    <Select.Value /><ChevronDown className="w-3 h-3 opacity-50" />
                  </Select.Trigger>
                  <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] rounded-lg border border-border bg-card shadow-sm p-1">
                    {Object.entries(PRIORITY_META).map(([k, { label, icon: Icon, color }]) => (
                      <Select.Item key={k} value={k} className="flex items-center gap-2 px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                        <Icon className={cn("w-3 h-3", color)} /><Select.ItemText>{label}</Select.ItemText>
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </div>
            </div>

            {/* Assignee */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Assign to agent <span className="opacity-50">(optional)</span></label>
              <Select.Root value={agentId} onValueChange={setAgentId}>
                <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-xs focus:outline-none">
                  <Select.Value placeholder="Unassigned" /><ChevronDown className="w-3 h-3 opacity-50" />
                </Select.Trigger>
                <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
                  <Select.Item value="__none__" className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent text-muted-foreground">
                    <Select.ItemText>Unassigned</Select.ItemText>
                  </Select.Item>
                  {agents.map(a => (
                    <Select.Item key={a.id} value={a.id} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                      <Select.ItemText>{a.name}</Select.ItemText>
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </div>

            {/* Labels */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Labels <span className="opacity-50">(comma-separated)</span></label>
              <Input value={labelsText} onChange={e => setLabelsText(e.target.value)} className="h-8 text-sm" placeholder="bug, frontend, urgent" />
            </div>
          </div>

          <div className="flex gap-2 justify-end px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" onClick={onClose} disabled={create.isPending}>Cancel</Button>
            <Button size="sm" onClick={() => create.mutate()} disabled={!canSubmit || create.isPending}>
              {create.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}Create Issue
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Filter Bar ───────────────────────────────────────────────────────────────

function IssueFilters({
  statusFilter, setStatusFilter,
  priorityFilter, setPriorityFilter,
  projectFilter, setProjectFilter,
  search, setSearch,
  projects,
}: {
  statusFilter: string; setStatusFilter: (v: string) => void;
  priorityFilter: string; setPriorityFilter: (v: string) => void;
  projectFilter: string; setProjectFilter: (v: string) => void;
  search: string; setSearch: (v: string) => void;
  projects: Project[];
}) {
  const hasFilters = statusFilter || priorityFilter || projectFilter || search;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Search */}
      <div className="relative flex-1 min-w-[180px] max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <Input
          value={search} onChange={e => setSearch(e.target.value)}
          className="h-8 text-xs pl-8 pr-8" placeholder="Search issues..."
        />
        {search && (
          <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Status */}
      <Select.Root value={statusFilter} onValueChange={setStatusFilter}>
        <Select.Trigger className="flex h-8 items-center gap-1.5 rounded-md border border-input bg-transparent px-2.5 text-xs focus:outline-none shrink-0">
          <Filter className="w-3 h-3 opacity-50" /><Select.Value placeholder="Status" /><ChevronDown className="w-3 h-3 opacity-50" />
        </Select.Trigger>
        <Select.Content position="popper" sideOffset={4} className="z-[200] min-w-[120px] rounded-lg border border-border bg-card shadow-sm p-1">
          <Select.Item value="__all__" className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>All statuses</Select.ItemText></Select.Item>
          {Object.entries(STATUS_META).map(([k, { label }]) => (
            <Select.Item key={k} value={k} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>{label}</Select.ItemText></Select.Item>
          ))}
        </Select.Content>
      </Select.Root>

      {/* Priority */}
      <Select.Root value={priorityFilter} onValueChange={setPriorityFilter}>
        <Select.Trigger className="flex h-8 items-center gap-1.5 rounded-md border border-input bg-transparent px-2.5 text-xs focus:outline-none shrink-0">
          <Select.Value placeholder="Priority" /><ChevronDown className="w-3 h-3 opacity-50" />
        </Select.Trigger>
        <Select.Content position="popper" sideOffset={4} className="z-[200] min-w-[120px] rounded-lg border border-border bg-card shadow-sm p-1">
          <Select.Item value="__all__" className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>All priorities</Select.ItemText></Select.Item>
          {Object.entries(PRIORITY_META).map(([k, { label }]) => (
            <Select.Item key={k} value={k} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>{label}</Select.ItemText></Select.Item>
          ))}
        </Select.Content>
      </Select.Root>

      {/* Project */}
      {projects.length > 0 && (
        <Select.Root value={projectFilter} onValueChange={setProjectFilter}>
          <Select.Trigger className="flex h-8 items-center gap-1.5 rounded-md border border-input bg-transparent px-2.5 text-xs focus:outline-none shrink-0">
            <FolderKanban className="w-3 h-3 opacity-50" /><Select.Value placeholder="Project" /><ChevronDown className="w-3 h-3 opacity-50" />
          </Select.Trigger>
          <Select.Content position="popper" sideOffset={4} className="z-[200] min-w-[140px] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
            <Select.Item value="__all__" className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>All projects</Select.ItemText></Select.Item>
            {projects.map(p => (
              <Select.Item key={p.id} value={p.id} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent"><Select.ItemText>{p.name}</Select.ItemText></Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
      )}

      {/* Clear all */}
      {hasFilters && (
        <button
          onClick={() => { setStatusFilter(""); setPriorityFilter(""); setProjectFilter(""); setSearch(""); }}
          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function IssuesPage() {
  const router = useRouter();
  const [createOpen, setCreateOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [search, setSearch] = useState("");

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then(r => r.data),
  });

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });

  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (statusFilter && statusFilter !== "__all__") p.status = statusFilter;
    if (priorityFilter && priorityFilter !== "__all__") p.priority = priorityFilter;
    if (projectFilter && projectFilter !== "__all__") p.project_id = projectFilter;
    if (search) p.search = search;
    return p;
  }, [statusFilter, priorityFilter, projectFilter, search]);

  const { data, isLoading } = useQuery<{ items: Issue[]; total: number }>({
    queryKey: ["issues", queryParams],
    queryFn: () => issuesApi.list(queryParams).then(r => r.data),
    refetchInterval: 8000,
  });

  const issues = data?.items ?? [];
  const total = data?.total ?? 0;

  // Stats
  const openCount = issues.filter(i => i.status === "open").length;
  const inProgressCount = issues.filter(i => i.status === "in_progress").length;

  return (
    <PageShell>
      <PageHeader
        icon={CircleDot}
        title="Issues"
        subtitle={
          <>
            {total} total
            {openCount > 0 && <> · <span className="text-green-400">{openCount} open</span></>}
            {inProgressCount > 0 && <> · <span className="text-blue-400">{inProgressCount} in progress</span></>}
          </>
        }
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />New Issue
          </Button>
        }
      />

      <div className="px-6 py-2.5 border-b border-border shrink-0">
        <IssueFilters
          statusFilter={statusFilter} setStatusFilter={setStatusFilter}
          priorityFilter={priorityFilter} setPriorityFilter={setPriorityFilter}
          projectFilter={projectFilter} setProjectFilter={setProjectFilter}
          search={search} setSearch={setSearch}
          projects={projects}
        />
      </div>

      <PageBody>
        {isLoading ? (
          <PageLoading />
        ) : issues.length === 0 ? (
          <PageEmpty
            icon={CircleDot}
            message={
              search || statusFilter || priorityFilter || projectFilter
                ? "No issues found — try adjusting your filters"
                : "No issues yet — create your first issue to start tracking work"
            }
          >
            {!search && !statusFilter && !priorityFilter && (
              <Button size="sm" onClick={() => setCreateOpen(true)}>Create first issue</Button>
            )}
          </PageEmpty>
        ) : (
          <div className="divide-y divide-border">
            {issues.map(issue => {
              const statusMeta = STATUS_META[issue.status] ?? STATUS_META.open;
              const priorityMeta = PRIORITY_META[issue.priority] ?? PRIORITY_META.medium;
              const PriorityIcon = priorityMeta.icon;

              return (
                <div
                  key={issue.id}
                  onClick={() => router.push(`/issues/${issue.id}`)}
                  className="flex items-start gap-3 px-6 py-3.5 hover:bg-accent/20 cursor-pointer transition-colors group"
                >
                  {/* Status dot */}
                  <span className={cn("w-2.5 h-2.5 rounded-full mt-1 shrink-0", statusMeta.dot)} />

                  {/* Main content */}
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-start gap-2">
                      <span className="text-sm font-medium leading-tight">{issue.title}</span>
                      {issue.external_ref && (
                        <Badge variant="outline" className="text-[10px] h-4 px-1.5 shrink-0 font-mono">
                          {issue.external_ref}
                        </Badge>
                      )}
                    </div>

                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
                      {/* Status badge */}
                      <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5 capitalize", statusMeta.color)}>
                        {statusMeta.label}
                      </Badge>

                      {/* Priority */}
                      <span className={cn("flex items-center gap-0.5", priorityMeta.color)}>
                        <PriorityIcon className="w-3 h-3" />{priorityMeta.label}
                      </span>

                      {/* Project */}
                      {issue.project_name && (
                        <span className="flex items-center gap-1">
                          <FolderKanban className="w-3 h-3" />{issue.project_name}
                        </span>
                      )}

                      {/* Assignee */}
                      {issue.assigned_agent_name && (
                        <span className="flex items-center gap-1 text-cyan-400/80">
                          <Bot className="w-3 h-3" />{issue.assigned_agent_name}
                        </span>
                      )}

                      {/* Comments */}
                      {issue.comment_count > 0 && (
                        <span className="flex items-center gap-0.5">
                          <MessageSquare className="w-3 h-3" />{issue.comment_count}
                        </span>
                      )}

                      {/* Labels */}
                      {issue.labels.slice(0, 3).map(l => (
                        <span key={l} className="px-1.5 py-0.5 bg-accent/60 rounded text-[10px] font-mono">{l}</span>
                      ))}
                      {issue.labels.length > 3 && (
                        <span className="text-[10px] opacity-60">+{issue.labels.length - 3}</span>
                      )}
                    </div>
                  </div>

                  {/* Time + arrow */}
                  <div className="flex items-center gap-2 shrink-0 text-[10px] text-muted-foreground mt-0.5">
                    <span>{fmtRelative(issue.created_at)}</span>
                    <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </PageBody>

      <CreateIssueDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        projects={projects}
        agents={agents}
      />
    </PageShell>
  );
}
