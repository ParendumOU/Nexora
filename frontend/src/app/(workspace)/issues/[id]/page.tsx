"use client";
import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { issuesApi, agentsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, Loader2, CircleDot, Bot, User as UserIcon,
  AlertTriangle, ArrowUp, Minus, ArrowDown,
  FolderKanban, ExternalLink, Link2, Send,
  Trash2, ChevronDown, Edit3, Save, X, MessageSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Select from "@radix-ui/react-select";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ─── Types ────────────────────────────────────────────────────────────────────

interface IssueComment {
  id: string;
  issue_id: string;
  author_agent_id: string | null;
  author_agent_name: string | null;
  author_user_id: string | null;
  author_user_name: string | null;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface IssueDetail {
  id: string;
  org_id: string;
  project_id: string;
  project_name: string | null;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  labels: string[];
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  reporter_agent_id: string | null;
  reporter_agent_name: string | null;
  reporter_user_id: string | null;
  reporter_user_name: string | null;
  linked_task_id: string | null;
  external_url: string | null;
  external_ref: string | null;
  comment_count: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  comments: IssueComment[];
}

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

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ─── Markdown Renderer ───────────────────────────────────────────────────────

function Markdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        h1:     ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
        h2:     ({ children }) => <h2 className="text-sm font-bold mb-1.5 mt-2.5 first:mt-0">{children}</h2>,
        h3:     ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
        ul:     ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
        ol:     ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
        li:     ({ children }) => <li className="text-sm">{children}</li>,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        a:      ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline">{children}</a>,
        pre:    ({ children }) => <pre className="overflow-auto rounded-lg bg-accent/40 border border-border p-3 mb-2 my-1">{children}</pre>,
        code:   ({ className, children }) => className
          ? <code className="text-xs font-mono">{children}</code>
          : <code className="px-1 py-0.5 bg-accent/60 rounded text-xs font-mono">{children}</code>,
        hr:     () => <hr className="border-border my-3" />,
      }}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ─── Comment Item ─────────────────────────────────────────────────────────────

function CommentItem({
  comment, onDelete,
}: {
  comment: IssueComment;
  onDelete: (id: string) => void;
}) {
  const isAgent = !!comment.author_agent_id;
  const authorName = isAgent ? comment.author_agent_name : comment.author_user_name;

  return (
    <div className="flex gap-3 group">
      {/* Avatar */}
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5",
        isAgent ? "bg-cyan-500/10 text-cyan-400" : "bg-primary/10 text-primary"
      )}>
        {isAgent ? <Bot className="w-4 h-4" /> : <UserIcon className="w-4 h-4" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-semibold">{authorName ?? "Unknown"}</span>
          {isAgent && <Badge variant="outline" className="text-[9px] h-3.5 px-1 text-cyan-400 border-cyan-500/20">agent</Badge>}
          <span className="text-[10px] text-muted-foreground">{fmtRelative(comment.created_at)}</span>
          <button
            onClick={() => onDelete(comment.id)}
            className="ml-auto opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-all"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
        <div className="bg-accent/20 rounded-xl px-4 py-3 border border-border/40">
          <Markdown content={comment.content} />
        </div>
      </div>
    </div>
  );
}

// ─── Sidebar Property ─────────────────────────────────────────────────────────

function SidebarProp({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      {children}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function IssueDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

  const { data: issue, isLoading } = useQuery<IssueDetail>({
    queryKey: ["issue", id],
    queryFn: () => issuesApi.get(id).then(r => r.data),
    enabled: !!id,
    refetchInterval: 10000,
  });

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });

  // ── Edit state ──
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [commentText, setCommentText] = useState("");

  useEffect(() => {
    if (issue) setTitleDraft(issue.title);
  }, [issue?.id]);

  // ── Mutations ──
  const updateIssue = useMutation({
    mutationFn: (data: Parameters<typeof issuesApi.update>[1]) => issuesApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issue", id] }); qc.invalidateQueries({ queryKey: ["issues"] }); },
    onError: () => toast.error("Failed to update issue"),
  });

  const addComment = useMutation({
    mutationFn: () => issuesApi.addComment(id, { content: commentText }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["issue", id] });
      setCommentText("");
      toast.success("Comment added");
    },
    onError: () => toast.error("Failed to add comment"),
  });

  const deleteComment = useMutation({
    mutationFn: (commentId: string) => issuesApi.deleteComment(id, commentId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issue", id] }); toast.success("Comment deleted"); },
    onError: () => toast.error("Failed to delete comment"),
  });

  const deleteIssue = useMutation({
    mutationFn: () => issuesApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issues"] }); toast.success("Issue deleted"); router.push("/issues"); },
    onError: () => toast.error("Failed to delete issue"),
  });

  if (isLoading || !issue) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
      </div>
    );
  }

  const statusMeta = STATUS_META[issue.status] ?? STATUS_META.open;
  const priorityMeta = PRIORITY_META[issue.priority] ?? PRIORITY_META.medium;
  const PriorityIcon = priorityMeta.icon;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center gap-3 shrink-0">
        <button onClick={() => router.push("/issues")} className="p-1.5 rounded hover:bg-accent text-muted-foreground transition-colors shrink-0">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <CircleDot className={cn("w-4 h-4 shrink-0", statusMeta.dot.includes("green") ? "text-green-400" : statusMeta.dot.includes("blue") ? "text-blue-400" : statusMeta.dot.includes("amber") ? "text-amber-400" : "text-muted-foreground")} />
        <div className="flex-1 min-w-0">
          {editingTitle ? (
            <div className="flex items-center gap-2">
              <Input value={titleDraft} onChange={e => setTitleDraft(e.target.value)} className="h-7 text-sm font-semibold" autoFocus />
              <button onClick={() => { updateIssue.mutate({ title: titleDraft }); setEditingTitle(false); }} className="p-1 text-green-400 hover:text-green-300"><Save className="w-3.5 h-3.5" /></button>
              <button onClick={() => { setTitleDraft(issue.title); setEditingTitle(false); }} className="p-1 text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>
            </div>
          ) : (
            <h1 className="text-sm font-semibold truncate cursor-pointer hover:text-primary transition-colors group flex items-center gap-1.5" onClick={() => setEditingTitle(true)}>
              {issue.title}
              <Edit3 className="w-3 h-3 opacity-0 group-hover:opacity-60 transition-opacity" />
            </h1>
          )}
          <div className="flex items-center gap-2 mt-0.5">
            {issue.external_ref && <Badge variant="outline" className="text-[10px] h-4 px-1.5 font-mono">{issue.external_ref}</Badge>}
            {issue.project_name && <span className="text-[10px] text-muted-foreground flex items-center gap-1"><FolderKanban className="w-3 h-3" />{issue.project_name}</span>}
          </div>
        </div>
        <button
          onClick={() => { if (confirm(`Delete "${issue.title}"?`)) deleteIssue.mutate(); }}
          className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors shrink-0"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Main content area */}
        <div className="flex-1 overflow-y-auto">
          {/* Description */}
          {issue.description && (
            <div className="px-6 py-5 border-b border-border">
              <Markdown content={issue.description} />
            </div>
          )}

          {/* Comments */}
          <div className="px-6 py-5 space-y-5">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5" />
              Comments
              {issue.comments.length > 0 && <span className="text-muted-foreground/60 font-normal">({issue.comments.length})</span>}
            </p>

            {issue.comments.length === 0 && (
              <p className="text-xs text-muted-foreground py-6 text-center">No comments yet. Be the first to comment or let an agent report progress.</p>
            )}

            {issue.comments.map(c => (
              <CommentItem
                key={c.id}
                comment={c}
                onDelete={cid => { if (confirm("Delete this comment?")) deleteComment.mutate(cid); }}
              />
            ))}

            {/* Add comment */}
            <div className="flex gap-3 pt-2">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <UserIcon className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1 space-y-2">
                <textarea
                  value={commentText}
                  onChange={e => setCommentText(e.target.value)}
                  rows={3}
                  className="w-full rounded-xl border border-border bg-accent/10 px-4 py-3 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground"
                  placeholder="Add a comment... (supports markdown)"
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={() => addComment.mutate()}
                    disabled={!commentText.trim() || addComment.isPending}
                    className="gap-1.5"
                  >
                    {addComment.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                    Comment
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="w-64 border-l border-border overflow-y-auto p-5 space-y-5 shrink-0 hidden lg:block">
          {/* Status */}
          <SidebarProp label="Status">
            <Select.Root value={issue.status} onValueChange={v => updateIssue.mutate({ status: v })}>
              <Select.Trigger className={cn("flex h-8 w-full items-center justify-between rounded-md border px-3 text-xs focus:outline-none", statusMeta.color)}>
                <Select.Value /><ChevronDown className="w-3 h-3 opacity-50" />
              </Select.Trigger>
              <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] rounded-lg border border-border bg-card shadow-sm p-1">
                {Object.entries(STATUS_META).map(([k, { label, dot }]) => (
                  <Select.Item key={k} value={k} className="flex items-center gap-2 px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                    <span className={cn("w-2 h-2 rounded-full", dot)} /><Select.ItemText>{label}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </SidebarProp>

          {/* Priority */}
          <SidebarProp label="Priority">
            <Select.Root value={issue.priority} onValueChange={v => updateIssue.mutate({ priority: v })}>
              <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-xs focus:outline-none">
                <span className={cn("flex items-center gap-1.5", priorityMeta.color)}>
                  <PriorityIcon className="w-3 h-3" /><Select.Value />
                </span>
                <ChevronDown className="w-3 h-3 opacity-50" />
              </Select.Trigger>
              <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] rounded-lg border border-border bg-card shadow-sm p-1">
                {Object.entries(PRIORITY_META).map(([k, { label, icon: Icon, color }]) => (
                  <Select.Item key={k} value={k} className="flex items-center gap-2 px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                    <Icon className={cn("w-3 h-3", color)} /><Select.ItemText>{label}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </SidebarProp>

          {/* Assignee */}
          <SidebarProp label="Assignee">
            <Select.Root
              value={issue.assigned_agent_id ?? "__none__"}
              onValueChange={v => updateIssue.mutate({ assigned_agent_id: v === "__none__" ? null : v })}
            >
              <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-xs focus:outline-none">
                <Select.Value placeholder="Unassigned" /><ChevronDown className="w-3 h-3 opacity-50" />
              </Select.Trigger>
              <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
                <Select.Item value="__none__" className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent text-muted-foreground">
                  <Select.ItemText>Unassigned</Select.ItemText>
                </Select.Item>
                {agents.map(a => (
                  <Select.Item key={a.id} value={a.id} className="flex items-center gap-2 px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                    <Bot className="w-3 h-3 text-muted-foreground" /><Select.ItemText>{a.name}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </SidebarProp>

          {/* Labels */}
          <SidebarProp label="Labels">
            {issue.labels.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {issue.labels.map(l => (
                  <span key={l} className="text-[10px] px-2 py-0.5 bg-accent/60 rounded font-mono">{l}</span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">None</p>
            )}
          </SidebarProp>

          {/* Reporter */}
          <SidebarProp label="Reporter">
            <div className="flex items-center gap-1.5 text-xs">
              {issue.reporter_agent_name ? (
                <><Bot className="w-3 h-3 text-cyan-400" />{issue.reporter_agent_name}</>
              ) : issue.reporter_user_name ? (
                <><UserIcon className="w-3 h-3 text-primary" />{issue.reporter_user_name}</>
              ) : (
                <span className="text-muted-foreground">Unknown</span>
              )}
            </div>
          </SidebarProp>

          {/* External link */}
          {issue.external_url && (
            <SidebarProp label="External">
              <a
                href={issue.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary hover:underline flex items-center gap-1 truncate"
              >
                <ExternalLink className="w-3 h-3 shrink-0" />
                {issue.external_ref || issue.external_url.replace(/^https?:\/\//, "").slice(0, 30)}
              </a>
            </SidebarProp>
          )}

          {/* Linked task */}
          {issue.linked_task_id && (
            <SidebarProp label="Linked Task">
              <span className="text-xs font-mono text-muted-foreground truncate block">
                <Link2 className="w-3 h-3 inline mr-1" />
                {issue.linked_task_id.slice(0, 8)}…
              </span>
            </SidebarProp>
          )}

          {/* Dates */}
          <SidebarProp label="Created">
            <span className="text-xs text-muted-foreground">{fmtDate(issue.created_at)}</span>
          </SidebarProp>
          {issue.closed_at && (
            <SidebarProp label="Closed">
              <span className="text-xs text-muted-foreground">{fmtDate(issue.closed_at)}</span>
            </SidebarProp>
          )}
        </div>
      </div>
    </div>
  );
}
