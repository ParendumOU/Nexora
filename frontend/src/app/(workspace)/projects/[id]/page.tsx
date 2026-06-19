"use client";
import { useState, useMemo, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import hljs from "highlight.js/lib/core";
import langPython from "highlight.js/lib/languages/python";
import langJS from "highlight.js/lib/languages/javascript";
import langTS from "highlight.js/lib/languages/typescript";
import langBash from "highlight.js/lib/languages/bash";
import langJSON from "highlight.js/lib/languages/json";
import langYAML from "highlight.js/lib/languages/yaml";
import langCSS from "highlight.js/lib/languages/css";
import langXML from "highlight.js/lib/languages/xml";
import langGo from "highlight.js/lib/languages/go";
import langRust from "highlight.js/lib/languages/rust";
import langJava from "highlight.js/lib/languages/java";
import langSQL from "highlight.js/lib/languages/sql";
import langMarkdown from "highlight.js/lib/languages/markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  FolderKanban, ArrowLeft, Bot, Wrench, Network, Key, CheckSquare,
  ScrollText, GitBranch, Calendar, Loader2, Plus, Trash2,
  Circle, CheckCircle2, AlertCircle, Pause, Play, Timer, Save,
  GitlabIcon, Github, ExternalLink, X, Lock, Globe, ChevronRight,
  ChevronDown, FileText, Folder, FolderOpen, RefreshCw, Settings,
  Eye, EyeOff, Code2, LayoutDashboard,
} from "lucide-react";
import { projectsApi, toolsApi, mcpServersApi, gitCredentialsApi, gitProxyApi } from "@/lib/api";
import Link from "next/link";

// Register highlight.js languages
hljs.registerLanguage("python", langPython);
hljs.registerLanguage("javascript", langJS);
hljs.registerLanguage("typescript", langTS);
hljs.registerLanguage("bash", langBash);
hljs.registerLanguage("shell", langBash);
hljs.registerLanguage("json", langJSON);
hljs.registerLanguage("yaml", langYAML);
hljs.registerLanguage("css", langCSS);
hljs.registerLanguage("html", langXML);
hljs.registerLanguage("xml", langXML);
hljs.registerLanguage("go", langGo);
hljs.registerLanguage("rust", langRust);
hljs.registerLanguage("java", langJava);
hljs.registerLanguage("sql", langSQL);
hljs.registerLanguage("markdown", langMarkdown);
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import {
  McpCapabilitySelector,
  type McpCapabilityServer,
  type McpCapabilitySelection,
} from "@/components/shared/McpCapabilitySelector";

// ─── Types ────────────────────────────────────────────────────────────────────

type Project = {
  id: string;
  name: string;
  description: string | null;
  repo_url: string | null;
  repo_type: string | null;
  repo_branch: string | null;
  repo_credential_id: string | null;
  is_private: boolean;
  status: string;
  pm_agent_id: string | null;
  pm_agent_name: string | null;
  tools: string[];
  mcps: McpCapabilitySelection[];
  env_vars: Record<string, string>;
  created_at: string;
  updated_at: string;
};

type GitCredential = {
  id: string;
  name: string;
  provider: string;
  color: string;
  base_url: string | null;
  token_hint: string;
};

type TreeNode = {
  name: string;
  path: string;
  type: "file" | "dir";
  children?: TreeNode[];
};

type Task = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  blocked_by: string[];
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

type ProjectAgent = {
  id: string;
  name: string;
  agent_type: string;
  description: string | null;
  skills: string[];
  is_pm: boolean;
  task_count: number;
};

// ─── Constants ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview",  label: "Overview",   Icon: FolderKanban },
  { id: "agents",    label: "Agents",     Icon: Bot },
  { id: "resources", label: "Resources",  Icon: Wrench },
  { id: "tasks",     label: "Tasks",      Icon: CheckSquare },
  { id: "logs",      label: "Logs",       Icon: ScrollText },
  { id: "repo",      label: "Repository", Icon: GitBranch },
] as const;
type TabId = (typeof TABS)[number]["id"];

const TASK_STATUS_CFG: Record<string, { label: string; Icon: React.ElementType; color: string }> = {
  running:   { label: "Running",   Icon: Play,         color: "text-cyan-400" },
  pending:   { label: "Pending",   Icon: Circle,       color: "text-yellow-400" },
  queued:    { label: "Queued",    Icon: Timer,        color: "text-blue-400" },
  paused:    { label: "Paused",    Icon: Pause,        color: "text-orange-400" },
  completed: { label: "Completed", Icon: CheckCircle2, color: "text-green-400" },
  failed:    { label: "Failed",    Icon: AlertCircle,  color: "text-red-400" },
};
const TASK_ORDER = ["running", "pending", "queued", "paused", "completed", "failed"] as const;

const LOG_COLORS: Record<string, string> = {
  debug: "text-muted-foreground",
  info:  "text-foreground",
  warn:  "text-yellow-400",
  error: "text-red-400",
};

const PRESET_COLORS = ["#6366f1","#ec4899","#f97316","#10b981","#3b82f6","#a855f7","#ef4444","#14b8a6"];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtRelative(iso: string) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function buildTree(items: { path: string; type: "file" | "dir" }[]): TreeNode[] {
  const root: TreeNode[] = [];
  const map = new Map<string, TreeNode>();

  const sorted = [...items].sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.path.localeCompare(b.path);
  });

  for (const item of sorted) {
    const parts = item.path.split("/");
    const name = parts[parts.length - 1];
    const node: TreeNode = { name, path: item.path, type: item.type, children: item.type === "dir" ? [] : undefined };
    map.set(item.path, node);

    if (parts.length === 1) {
      root.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      const parent = map.get(parentPath);
      if (parent?.children) {
        parent.children.push(node);
      }
    }
  }
  return root;
}

function getLanguage(filename: string): string {
  const lower = filename.toLowerCase();
  const ext = lower.split(".").pop() ?? "";
  if (lower === "dockerfile" || lower.startsWith("dockerfile.")) return "bash";
  if (lower === "makefile" || lower === "gemfile" || lower === "rakefile") return "bash";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", go: "go", rs: "rust", java: "java",
    json: "json", yaml: "yaml", yml: "yaml",
    md: "markdown", mdx: "markdown",
    html: "html", htm: "html", xml: "xml", svg: "xml",
    css: "css", scss: "css", sass: "css", less: "css",
    sh: "bash", bash: "bash", zsh: "bash", fish: "bash",
    sql: "sql", rb: "bash", php: "javascript",
    toml: "bash", ini: "bash", env: "bash",
  };
  return map[ext] ?? "plaintext";
}

// ─── File Viewer ──────────────────────────────────────────────────────────────

function FileViewer({ file, content, loading }: { file: TreeNode; content: string; loading: boolean }) {
  const [renderMarkdown, setRenderMarkdown] = useState(true);
  const lang = getLanguage(file.name);
  const isMarkdown = lang === "markdown";
  const isPlaintext = lang === "plaintext";

  const highlighted = useMemo(() => {
    if (!content || isPlaintext || isMarkdown) return "";
    try {
      if (hljs.getLanguage(lang)) {
        return hljs.highlight(content, { language: lang, ignoreIllegals: true }).value;
      }
      return hljs.highlightAuto(content).value;
    } catch {
      return "";
    }
  }, [content, lang, isPlaintext, isMarkdown]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col min-w-0">
      {/* File header */}
      <div className="px-4 py-2 border-b border-border flex items-center gap-2 shrink-0 bg-card">
        <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs font-mono text-muted-foreground truncate flex-1">{file.path}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[10px] px-1.5 py-0.5 bg-accent rounded text-muted-foreground font-mono">
            {lang === "plaintext" ? "text" : lang}
          </span>
          {isMarkdown && (
            <button
              onClick={() => setRenderMarkdown(r => !r)}
              className={cn(
                "flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border transition-colors",
                renderMarkdown
                  ? "bg-primary/10 border-primary/30 text-primary"
                  : "border-border text-muted-foreground hover:bg-accent"
              )}
            >
              {renderMarkdown ? <><Eye className="w-3 h-3" /> Rendered</> : <><Code2 className="w-3 h-3" /> Source</>}
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isMarkdown && renderMarkdown ? (
          <div className="p-6 text-sm leading-relaxed [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3 [&_h1]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mb-1 [&_h3]:mt-3 [&_p]:mb-3 [&_p]:text-muted-foreground [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_code]:font-mono [&_code]:text-xs [&_code]:bg-accent [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_pre]:bg-neutral-950 [&_pre]:rounded-lg [&_pre]:p-4 [&_pre]:overflow-auto [&_pre]:mb-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_blockquote]:italic [&_blockquote]:mb-3 [&_hr]:border-border [&_hr]:my-4 [&_a]:text-primary [&_a]:underline [&_table]:w-full [&_table]:text-xs [&_th]:text-left [&_th]:font-semibold [&_th]:border-b [&_th]:border-border [&_th]:pb-1 [&_th]:px-2 [&_td]:border-b [&_td]:border-border/40 [&_td]:py-1.5 [&_td]:px-2">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : highlighted ? (
          <pre className="hljs m-0 rounded-none h-full p-4 text-xs leading-5 overflow-auto">
            <code dangerouslySetInnerHTML={{ __html: highlighted }} />
          </pre>
        ) : (
          <pre className="p-4 text-xs leading-5 font-mono text-foreground overflow-auto whitespace-pre-wrap break-all">
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}

// ─── Shared micro ─────────────────────────────────────────────────────────────

function SectionHeader({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">{children}</p>
      {action}
    </div>
  );
}

function Loading() {
  return (
    <div className="flex items-center justify-center h-40 text-muted-foreground">
      <Loader2 className="w-5 h-5 animate-spin" />
    </div>
  );
}

function EmptyState({ icon: Icon, text }: { icon: React.ElementType; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
      <Icon className="w-10 h-10 opacity-20" />
      <p className="text-sm">{text}</p>
    </div>
  );
}

function PropRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div>{children}</div>
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({ project, onSave }: { project: Project; onSave: (d: Partial<Project>) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: project.name, description: project.description ?? "", repo_url: project.repo_url ?? "" });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSave({ name: form.name.trim() || project.name, description: form.description.trim() || undefined, repo_url: form.repo_url.trim() || undefined });
    setSaving(false);
    setEditing(false);
  };

  return (
    <div className="max-w-xl space-y-6">
      <div className="flex items-center justify-between">
        <SectionHeader>Project Details</SectionHeader>
        {!editing && <button onClick={() => setEditing(true)} className="text-xs text-muted-foreground hover:text-foreground">Edit</button>}
      </div>

      {editing ? (
        <div className="space-y-3">
          <div className="space-y-1"><label className="text-xs text-muted-foreground">Name</label>
            <Input value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} /></div>
          <div className="space-y-1"><label className="text-xs text-muted-foreground">Description</label>
            <Input value={form.description} onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))} placeholder="What are you building?" /></div>
          <div className="space-y-1"><label className="text-xs text-muted-foreground">Repository URL</label>
            <Input value={form.repo_url} onChange={(e) => setForm(f => ({ ...f, repo_url: e.target.value }))} placeholder="https://github.com/org/repo" /></div>
          <div className="flex gap-2 pt-1">
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}<Save className="w-3.5 h-3.5 mr-1" />Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <PropRow label="Status">
            <Badge variant="secondary" className={cn("text-[10px] h-4 px-1.5", project.status === "active" ? "text-green-400" : "")}>
              {project.status}
            </Badge>
          </PropRow>
          {project.description && <PropRow label="Description"><span className="text-xs">{project.description}</span></PropRow>}
          <PropRow label="Created"><span className="text-xs">{fmtDate(project.created_at)}</span></PropRow>
          <PropRow label="Updated"><span className="text-xs">{fmtDate(project.updated_at)}</span></PropRow>
          {project.repo_url && (
            <PropRow label="Repository">
              <a href={project.repo_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline flex items-center gap-1">
                <GitBranch className="w-3 h-3" />{project.repo_url.replace("https://", "")}<ExternalLink className="w-3 h-3" />
              </a>
            </PropRow>
          )}
          {project.pm_agent_name && (
            <PropRow label="PM Agent"><span className="text-xs flex items-center gap-1"><Bot className="w-3 h-3 text-primary" />{project.pm_agent_name}</span></PropRow>
          )}
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 pt-2">
        {[{ label: "Tools", value: project.tools.length, Icon: Wrench }, { label: "MCP Servers", value: project.mcps.length, Icon: Network }, { label: "Env Vars", value: Object.keys(project.env_vars).length, Icon: Key }].map(({ label, value, Icon }) => (
          <div key={label} className="border border-border rounded-lg p-3 text-center space-y-1">
            <Icon className="w-4 h-4 mx-auto text-muted-foreground" />
            <p className="text-lg font-bold">{value}</p>
            <p className="text-[10px] text-muted-foreground">{label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Agents Tab ───────────────────────────────────────────────────────────────

function AgentsTab({ projectId }: { projectId: string }) {
  const { data: agents = [], isLoading } = useQuery<ProjectAgent[]>({
    queryKey: ["project-agents", projectId],
    queryFn: () => projectsApi.agents(projectId).then(r => r.data),
  });
  if (isLoading) return <Loading />;
  if (!agents.length) return <EmptyState icon={Bot} text="No agents have worked on this project yet" />;

  return (
    <div className="space-y-3">
      <SectionHeader>Active Agents ({agents.length})</SectionHeader>
      {agents.map(agent => (
        <div key={agent.id} className="border border-border rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <Bot className="w-5 h-5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">{agent.name}</p>
                {agent.is_pm && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">PM</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">{agent.agent_type}</p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-sm font-semibold">{agent.task_count}</p>
              <p className="text-[10px] text-muted-foreground">tasks</p>
            </div>
          </div>
          {agent.description && <p className="text-xs text-muted-foreground">{agent.description}</p>}
          {agent.skills.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.skills.map(s => <span key={s} className="text-[10px] px-1.5 py-0.5 bg-accent rounded font-mono">{s}</span>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Resources Tab ────────────────────────────────────────────────────────────

function ResourcesTab({ project, onSave }: { project: Project; onSave: (d: Partial<Project>) => Promise<void> }) {
  const [resTab, setResTab] = useState<"tools" | "mcps" | "env">("tools");
  const [tools, setTools] = useState<string[]>(project.tools ?? []);
  const [mcps, setMcps] = useState<McpCapabilitySelection[]>(project.mcps ?? []);
  const [envVars, setEnvVars] = useState<{ key: string; value: string }[]>(
    Object.entries(project.env_vars ?? {}).map(([key, value]) => ({ key, value }))
  );
  const [saving, setSaving] = useState(false);
  const [toolSearch, setToolSearch] = useState("");

  // Merge builtin + custom tools
  const { data: builtinTools = [] } = useQuery({ queryKey: ["tools-builtin"], queryFn: () => toolsApi.builtin().then(r => r.data) });
  const { data: customTools = [] } = useQuery({ queryKey: ["tools"], queryFn: () => toolsApi.list().then(r => r.data) });
  const allTools = useMemo(() => {
    const keys = new Set((builtinTools as { key: string }[]).map(t => t.key));
    return [
      ...(builtinTools as { key: string; name: string; description: string | null; category: string }[]),
      ...(customTools as { key: string; name: string; description: string | null; category: string }[]).filter(t => !keys.has(t.key)),
    ];
  }, [builtinTools, customTools]);

  const { data: mcpCatalog = [] } = useQuery<McpCapabilityServer[]>({
    queryKey: ["mcp-servers"],
    queryFn: () => mcpServersApi.list().then(r =>
      r.data.map((s: { id: string; name: string; url: string; description: string | null; known_tools?: { name: string; description: string }[] }) => ({
        id: s.id, name: s.name, url: s.url, description: s.description,
        known_tools: (s.known_tools ?? []).map(t => ({ name: t.name, description: t.description })),
      }))
    ),
  });

  const filteredTools = useMemo(() => {
    const q = toolSearch.toLowerCase();
    return allTools.filter(t => !q || t.name.toLowerCase().includes(q) || (t.description ?? "").toLowerCase().includes(q));
  }, [allTools, toolSearch]);

  const handleToggleTool = (key: string) =>
    setTools(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]);

  const handleSave = async () => {
    setSaving(true);
    const env_vars = Object.fromEntries(envVars.filter(e => e.key.trim()).map(e => [e.key.trim(), e.value]));
    await onSave({ tools, mcps, env_vars });
    setSaving(false);
  };

  const RES_TABS = [
    { id: "tools", label: `Tools (${tools.length})`, Icon: Wrench },
    { id: "mcps",  label: `MCP Servers (${mcps.length})`, Icon: Network },
    { id: "env",   label: `Env Vars (${envVars.length})`, Icon: Key },
  ] as const;

  return (
    <div className="space-y-4 max-w-2xl">
      {/* Sub-tabs */}
      <div className="flex gap-1 border-b border-border pb-0">
        {RES_TABS.map(({ id, label, Icon }) => (
          <button key={id} onClick={() => setResTab(id)}
            className={cn("flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors",
              resTab === id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {resTab === "tools" && (
        <div className="space-y-2">
          <Input value={toolSearch} onChange={e => setToolSearch(e.target.value)}
            placeholder="Search tools…" className="h-8 text-xs" />
          <div className="border border-border rounded-lg overflow-hidden">
            <div className="overflow-y-auto max-h-96">
              <table className="w-full text-xs">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-accent/40 border-b border-border">
                    <th className="w-9 px-3 py-2" />
                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Name</th>
                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Category</th>
                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {filteredTools.length === 0
                    ? <tr><td colSpan={4} className="text-center py-8 text-muted-foreground">No tools found</td></tr>
                    : filteredTools.map(tool => {
                        const isOn = tools.includes(tool.key);
                        return (
                          <tr key={tool.key} onClick={() => handleToggleTool(tool.key)}
                            className={cn("cursor-pointer transition-colors", isOn ? "bg-primary/5 hover:bg-primary/8" : "hover:bg-accent/30")}>
                            <td className="px-3 py-2.5">
                              <div className={cn("w-4 h-4 rounded border flex items-center justify-center", isOn ? "bg-primary border-primary" : "border-border bg-background")}>
                                {isOn && <span className="text-[9px] text-primary-foreground font-bold">✓</span>}
                              </div>
                            </td>
                            <td className="px-3 py-2.5 font-medium whitespace-nowrap">{tool.name}</td>
                            <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">{tool.category}</td>
                            <td className="px-3 py-2.5 text-muted-foreground line-clamp-1 max-w-xs">{tool.description ?? "—"}</td>
                          </tr>
                        );
                      })
                  }
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {resTab === "mcps" && (
        <McpCapabilitySelector
          catalogMcps={mcpCatalog}
          selectedMcps={mcps}
          onToggleMcp={mcp => setMcps(prev => {
            const exists = prev.some(m => m.server_id === mcp.id || m.name === mcp.name);
            return exists ? prev.filter(m => m.server_id !== mcp.id && m.name !== mcp.name)
              : [...prev, { server_id: mcp.id, name: mcp.name, url: mcp.url }];
          })}
          onSetAllowedTools={(mcp, tools) => setMcps(prev => prev.map(m =>
            (m.server_id === mcp.id || m.name === mcp.name)
              ? { ...m, allowed_tools: tools.length > 0 ? tools : undefined }
              : m
          ))}
          emptyText="No MCP servers configured. Add servers in the MCP section first."
        />
      )}

      {resTab === "env" && (
        <div className="space-y-2">
          <div className="flex justify-end">
            <button onClick={() => setEnvVars(prev => [...prev, { key: "", value: "" }])}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
              <Plus className="w-3 h-3" />Add variable
            </button>
          </div>
          {envVars.length === 0
            ? <p className="text-xs text-muted-foreground text-center py-8">No environment variables configured</p>
            : envVars.map((ev, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <Input value={ev.key} onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, key: e.target.value } : x))}
                    placeholder="KEY" className="font-mono text-xs h-8 w-44 shrink-0" />
                  <span className="text-muted-foreground text-xs shrink-0">=</span>
                  <Input value={ev.value} onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
                    placeholder="value" className="font-mono text-xs h-8 flex-1" />
                  <button onClick={() => setEnvVars(prev => prev.filter((_, j) => j !== i))}
                    className="p-1 text-muted-foreground hover:text-destructive transition-colors shrink-0">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
          }
        </div>
      )}

      <Button onClick={handleSave} disabled={saving} size="sm">
        {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />}
        <Save className="w-3.5 h-3.5 mr-1.5" />Save Resources
      </Button>
    </div>
  );
}

// ─── Tasks Tab ────────────────────────────────────────────────────────────────

function TasksTab({ projectId }: { projectId: string }) {
  const { data: tasks = [], isLoading } = useQuery<Task[]>({
    queryKey: ["project-tasks", projectId],
    queryFn: () => projectsApi.tasks(projectId).then(r => r.data),
    refetchInterval: 15000,
  });
  if (isLoading) return <Loading />;

  const grouped = TASK_ORDER.reduce<Record<string, Task[]>>((acc, s) => {
    acc[s] = tasks.filter(t => t.status === s);
    return acc;
  }, {} as Record<string, Task[]>);
  const total = tasks.length;
  const done = tasks.filter(t => t.status === "completed").length;

  return (
    <div className="space-y-5">
      {total > 0 && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{done}/{total} completed</span>
            <span>{Math.round((done / total) * 100)}%</span>
          </div>
          <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
            <div className="h-full bg-green-400 rounded-full transition-all" style={{ width: `${(done / total) * 100}%` }} />
          </div>
        </div>
      )}
      <div className="flex items-center justify-between mb-1">
        <span />
        <Link href={`/projects/${projectId}/board`} className="text-xs text-primary hover:underline flex items-center gap-1">
          <LayoutDashboard className="w-3 h-3" />View board
        </Link>
      </div>
      {total === 0
        ? <EmptyState icon={CheckSquare} text="No tasks yet — they are created by the PM agent or via conversations" />
        : TASK_ORDER.map(status => {
            const list = grouped[status];
            if (!list?.length) return null;
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
                  {list.map(task => (
                    <div key={task.id} className="p-3 border border-border/60 rounded-lg space-y-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-start gap-1.5 flex-1 min-w-0">
                          {task.priority && task.priority !== "medium" && (
                            <span className={cn(
                              "shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide mt-0.5",
                              task.priority === "critical" ? "bg-red-400/15 text-red-400" :
                              task.priority === "high"     ? "bg-orange-400/15 text-orange-400" :
                              "bg-slate-400/15 text-slate-400"
                            )}>
                              {task.priority}
                            </span>
                          )}
                          <p className="text-xs font-medium">{task.title}</p>
                        </div>
                        {task.assigned_agent_name && (
                          <span className="text-[10px] text-muted-foreground shrink-0 flex items-center gap-1">
                            <Bot className="w-3 h-3" />{task.assigned_agent_name}
                          </span>
                        )}
                      </div>
                      {task.description && <p className="text-[11px] text-muted-foreground line-clamp-2">{task.description}</p>}
                      {task.checklist.length > 0 && (
                        <div className="space-y-0.5">
                          {task.checklist.slice(0, 3).map(item => (
                            <div key={item.id} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                              <div className={cn("w-3 h-3 rounded-sm border flex items-center justify-center shrink-0",
                                item.done ? "bg-green-500/20 border-green-500/40" : "border-border")}>
                                {item.done && <span className="text-[7px] text-green-400">✓</span>}
                              </div>
                              {item.item}
                            </div>
                          ))}
                          {task.checklist.length > 3 && <p className="text-[10px] text-muted-foreground pl-4">+{task.checklist.length - 3} more</p>}
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
          })
      }
    </div>
  );
}

// ─── Logs Tab ─────────────────────────────────────────────────────────────────

function LogsTab({ projectId }: { projectId: string }) {
  const { data: logs = [], isLoading } = useQuery<LogEntry[]>({
    queryKey: ["project-logs", projectId],
    queryFn: () => projectsApi.logs(projectId).then(r => r.data),
    refetchInterval: 10000,
  });
  if (isLoading) return <Loading />;
  if (!logs.length) return <EmptyState icon={ScrollText} text="No logs yet" />;

  return (
    <div className="bg-neutral-950 rounded-lg p-4 font-mono text-xs space-y-0.5 overflow-auto max-h-[calc(100vh-280px)]">
      {logs.map(log => (
        <div key={log.id} className="flex gap-2 leading-5">
          <span className="text-muted-foreground/40 shrink-0 select-none tabular-nums">
            {new Date(log.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
          {log.agent_name && <span className="text-blue-300 shrink-0">[{log.agent_name}]</span>}
          <span className={LOG_COLORS[log.level] ?? "text-foreground"}>{log.message}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Credentials Modal ────────────────────────────────────────────────────────

function CredentialsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: creds = [], isLoading } = useQuery<GitCredential[]>({
    queryKey: ["git-credentials"],
    queryFn: () => gitCredentialsApi.list().then(r => r.data),
    enabled: open,
  });
  const [form, setForm] = useState({ name: "", provider: "github", token: "", color: PRESET_COLORS[0], base_url: "" });
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);

  const deleteMut = useMutation({
    mutationFn: (id: string) => gitCredentialsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["git-credentials"] }),
  });

  const handleCreate = async () => {
    if (!form.name.trim() || !form.token.trim()) { toast.error("Name and token are required"); return; }
    setSaving(true);
    try {
      await gitCredentialsApi.create({ name: form.name.trim(), provider: form.provider, token: form.token.trim(), color: form.color, base_url: form.base_url.trim() || undefined });
      qc.invalidateQueries({ queryKey: ["git-credentials"] });
      toast.success("Credential added");
      setForm({ name: "", provider: "github", token: "", color: PRESET_COLORS[0], base_url: "" });
    } catch { toast.error("Failed to save credential"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-2xl shadow-2xl p-6 space-y-5">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold">Git Credentials</Dialog.Title>
            <button onClick={onClose} className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-4 h-4" /></button>
          </div>

          {/* Existing credentials */}
          {isLoading ? <Loading /> : creds.length === 0
            ? <p className="text-xs text-muted-foreground text-center py-4">No credentials yet</p>
            : (
              <div className="border border-border rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-accent/40 border-b border-border">
                      <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Name</th>
                      <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Provider</th>
                      <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Token</th>
                      <th className="w-8 px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {creds.map(c => (
                      <tr key={c.id} className="hover:bg-accent/20">
                        <td className="px-3 py-2.5 flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: c.color }} />
                          {c.name}
                        </td>
                        <td className="px-3 py-2.5 capitalize text-muted-foreground">{c.provider}</td>
                        <td className="px-3 py-2.5 font-mono text-muted-foreground">{c.token_hint}</td>
                        <td className="px-3 py-2.5">
                          <button onClick={() => deleteMut.mutate(c.id)} className="text-muted-foreground hover:text-destructive">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }

          {/* Add new */}
          <div className="border-t border-border pt-4 space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Add credential</p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><label className="text-xs text-muted-foreground">Name</label>
                <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="My GitHub" className="h-8 text-xs" /></div>
              <div className="space-y-1"><label className="text-xs text-muted-foreground">Provider</label>
                <div className="flex gap-1">
                  {["github", "gitlab"].map(p => (
                    <button key={p} onClick={() => setForm(f => ({ ...f, provider: p }))}
                      className={cn("flex-1 text-xs py-1.5 rounded border transition-colors",
                        form.provider === p ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="space-y-1"><label className="text-xs text-muted-foreground">Personal Access Token</label>
              <div className="relative">
                <Input type={showToken ? "text" : "password"} value={form.token}
                  onChange={e => setForm(f => ({ ...f, token: e.target.value }))}
                  placeholder="ghp_… or glpat-…" className="h-8 text-xs pr-8 font-mono" />
                <button onClick={() => setShowToken(s => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                  {showToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            {form.provider === "gitlab" && (
              <div className="space-y-1"><label className="text-xs text-muted-foreground">Base URL (self-hosted, optional)</label>
                <Input value={form.base_url} onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
                  placeholder="https://gitlab.mycompany.com" className="h-8 text-xs" /></div>
            )}
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Color</label>
              <div className="flex gap-1.5">
                {PRESET_COLORS.map(c => (
                  <button key={c} onClick={() => setForm(f => ({ ...f, color: c }))}
                    style={{ background: c }}
                    className={cn("w-6 h-6 rounded-full border-2 transition-transform", form.color === c ? "border-foreground scale-110" : "border-transparent")} />
                ))}
              </div>
            </div>
            <Button size="sm" onClick={handleCreate} disabled={saving}>
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />}
              <Plus className="w-3.5 h-3.5 mr-1.5" />Add Credential
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── File Tree Node ────────────────────────────────────────────────────────────

function FileTreeNode({ node, depth, onSelect, selected }: {
  node: TreeNode; depth: number; onSelect: (n: TreeNode) => void; selected: string | null;
}) {
  const [open, setOpen] = useState(depth === 0 && node.type === "dir");
  const isSelected = selected === node.path;

  if (node.type === "dir") {
    return (
      <div>
        <button onClick={() => setOpen(o => !o)}
          style={{ paddingLeft: `${depth * 14 + 10}px` }}
          className="flex items-center gap-1.5 w-full py-[3px] pr-3 text-xs hover:bg-accent/40 rounded transition-colors text-left">
          {open ? <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" /> : <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />}
          {open ? <FolderOpen className="w-3.5 h-3.5 text-yellow-400 shrink-0" /> : <Folder className="w-3.5 h-3.5 text-yellow-400 shrink-0" />}
          <span className="truncate">{node.name}</span>
        </button>
        {open && node.children?.map(child => (
          <FileTreeNode key={child.path} node={child} depth={depth + 1} onSelect={onSelect} selected={selected} />
        ))}
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelect(node)}
      style={{ paddingLeft: `${depth * 14 + 26}px` }}
      className={cn("flex items-center gap-1.5 w-full py-[3px] pr-3 text-xs rounded transition-colors text-left",
        isSelected ? "bg-primary/10 text-primary" : "hover:bg-accent/40")}
    >
      <FileText className="w-3.5 h-3.5 shrink-0" style={{ color: isSelected ? undefined : "oklch(var(--muted-foreground))" }} />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

// ─── Repository Tab ────────────────────────────────────────────────────────────

function RepoTab({ project, onSave }: { project: Project; onSave: (d: Partial<Project>) => Promise<void> }) {
  const [showCredModal, setShowCredModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState(project.repo_url ?? "");
  const [repoType, setRepoType] = useState(project.repo_type ?? "github");
  const [isPrivate, setIsPrivate] = useState(project.is_private ?? false);
  const [credId, setCredId] = useState(project.repo_credential_id ?? "");
  const [branch, setBranch] = useState(project.repo_branch ?? "");
  const [selectedFile, setSelectedFile] = useState<TreeNode | null>(null);
  const [saving, setSaving] = useState(false);

  const { data: creds = [] } = useQuery<GitCredential[]>({
    queryKey: ["git-credentials"],
    queryFn: () => gitCredentialsApi.list().then(r => r.data),
  });

  const { data: branches = [], isLoading: loadingBranches, refetch: fetchBranches } = useQuery<{ name: string }[]>({
    queryKey: ["git-branches", credId, repoUrl],
    queryFn: () => gitProxyApi.branches(credId, repoUrl).then(r => r.data),
    enabled: false,
  });

  const effectiveBranch = branch || "main";
  const { data: treeItems = [], isLoading: loadingTree, refetch: fetchTree } = useQuery<{ path: string; type: "file" | "dir" }[]>({
    queryKey: ["git-tree", credId, repoUrl, effectiveBranch],
    queryFn: () => gitProxyApi.tree(credId, repoUrl, effectiveBranch).then(r => r.data),
    enabled: false,
  });

  const { data: fileContent, isLoading: loadingFile } = useQuery<{ content: string }>({
    queryKey: ["git-file", credId, repoUrl, selectedFile?.path, effectiveBranch],
    queryFn: () => gitProxyApi.file(credId, repoUrl, selectedFile!.path, effectiveBranch).then(r => r.data),
    enabled: !!selectedFile && !!credId && !!repoUrl,
  });

  const tree = useMemo(() => buildTree(treeItems), [treeItems]);

  const handleSaveSettings = async () => {
    setSaving(true);
    await onSave({ repo_url: repoUrl || undefined, repo_type: repoType, repo_branch: branch || undefined, repo_credential_id: credId || undefined, is_private: isPrivate });
    setSaving(false);
  };

  const handleLoadTree = async () => {
    if (!credId || !repoUrl) { toast.error("Select a credential and enter the repository URL first"); return; }
    try {
      await fetchBranches();
      await fetchTree();
    } catch {
      toast.error("Failed to fetch repository — check URL and credentials");
    }
  };

  const hasTree = treeItems.length > 0;

  return (
    <div className="flex h-full min-h-0">
      {/* Left panel — settings */}
      <div className="w-80 shrink-0 border-r border-border p-5 overflow-y-auto space-y-4">
        <SectionHeader action={
          <button onClick={() => setShowCredModal(true)} className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
            <Settings className="w-3 h-3" />Manage
          </button>
        }>Repository</SectionHeader>

        {/* URL */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Repository URL</label>
          <div className="flex gap-1.5">
            {["github", "gitlab"].map(t => (
              <button key={t} onClick={() => setRepoType(t)}
                className={cn("flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors",
                  repoType === t ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}>
                {t === "github" ? <Github className="w-3 h-3" /> : <GitlabIcon className="w-3 h-3" />}
                {t}
              </button>
            ))}
          </div>
          <Input value={repoUrl} onChange={e => setRepoUrl(e.target.value)}
            placeholder={repoType === "github" ? "https://github.com/org/repo" : "https://gitlab.com/org/repo"}
            className="text-xs h-8" />
        </div>

        {/* Visibility */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Visibility</label>
          <div className="flex gap-1.5">
            {[{ v: false, label: "Public", Icon: Globe }, { v: true, label: "Private", Icon: Lock }].map(({ v, label, Icon }) => (
              <button key={label} onClick={() => setIsPrivate(v)}
                className={cn("flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border flex-1 justify-center transition-colors",
                  isPrivate === v ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}>
                <Icon className="w-3 h-3" />{label}
              </button>
            ))}
          </div>
        </div>

        {/* Credentials */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Credentials</label>
          {creds.length === 0
            ? <button onClick={() => setShowCredModal(true)} className="text-xs text-muted-foreground hover:text-primary flex items-center gap-1">
                <Plus className="w-3 h-3" />Add credentials
              </button>
            : <select value={credId} onChange={e => setCredId(e.target.value)}
                className="w-full h-8 text-xs border border-border rounded-md bg-background px-2 focus:outline-none focus:ring-1 focus:ring-ring">
                <option value="">— select credentials —</option>
                {creds.map(c => <option key={c.id} value={c.id}>{c.name} ({c.provider})</option>)}
              </select>
          }
        </div>

        {/* Branch */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Branch</label>
          <div className="flex gap-1.5">
            {branches.length > 0
              ? <select value={branch} onChange={e => setBranch(e.target.value)}
                  className="flex-1 h-8 text-xs border border-border rounded-md bg-background px-2 focus:outline-none focus:ring-1 focus:ring-ring">
                  <option value="">main</option>
                  {branches.map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
                </select>
              : <Input value={branch} onChange={e => setBranch(e.target.value)} placeholder="main" className="text-xs h-8 flex-1" />
            }
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 pt-1">
          <Button size="sm" onClick={handleLoadTree} disabled={loadingTree || loadingBranches} className="w-full">
            {(loadingTree || loadingBranches) ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
            {hasTree ? "Refresh Tree" : "Load Repository"}
          </Button>
          <Button size="sm" variant="outline" onClick={handleSaveSettings} disabled={saving} className="w-full">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />}
            <Save className="w-3.5 h-3.5 mr-1.5" />Save Settings
          </Button>
        </div>

        {repoUrl && (
          <a href={repoUrl} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary">
            <ExternalLink className="w-3 h-3" />Open in {repoType}
          </a>
        )}
      </div>

      {/* Right panel — file tree + viewer */}
      <div className="flex-1 flex min-w-0">
        {/* File tree */}
        <div className="w-56 shrink-0 border-r border-border overflow-y-auto overflow-x-hidden">
          {loadingTree
            ? <div className="flex items-center justify-center h-32 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /></div>
            : !hasTree
              ? <div className="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground p-4 text-center">
                  <Folder className="w-8 h-8 opacity-20" />
                  <p className="text-xs">Select credentials, enter a repo URL, and click Load</p>
                </div>
              : <div className="py-2 font-mono">
                  {tree.map(node => (
                    <FileTreeNode key={node.path} node={node} depth={0} onSelect={setSelectedFile} selected={selectedFile?.path ?? null} />
                  ))}
                </div>
          }
        </div>

        {/* File viewer */}
        <div className="flex-1 min-w-0 overflow-hidden">
          {!selectedFile
            ? <div className="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground">
                <FileText className="w-8 h-8 opacity-20" />
                <p className="text-xs">Select a file to view its content</p>
              </div>
            : <FileViewer
                file={selectedFile}
                content={fileContent?.content ?? ""}
                loading={loadingFile}
              />
          }
        </div>
      </div>

      <CredentialsModal open={showCredModal} onClose={() => setShowCredModal(false)} />
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ProjectWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const { data: project, isLoading, error } = useQuery<Project>({
    queryKey: ["project", params.id],
    queryFn: () => projectsApi.get(params.id).then(r => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: (data: Partial<Project>) => projectsApi.update(params.id, data),
    onSuccess: res => {
      qc.setQueryData(["project", params.id], res.data);
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  const handleSave = useCallback(async (data: Partial<Project>) => {
    await updateMutation.mutateAsync(data);
  }, [updateMutation]);

  const deleteMutation = useMutation({
    mutationFn: () => projectsApi.delete(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Project deleted");
      router.push("/projects");
    },
  });

  if (isLoading) return (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading project…
    </div>
  );

  if (error || !project) return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
      <FolderKanban className="w-10 h-10 opacity-20" />
      <p>Project not found</p>
      <Button variant="outline" size="sm" onClick={() => router.push("/projects")}>
        <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />Back to Projects
      </Button>
    </div>
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center gap-4 shrink-0">
        <button onClick={() => router.push("/projects")}
          className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground shrink-0">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <FolderKanban className="w-5 h-5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold truncate">{project.name}</h1>
          {project.description && <p className="text-xs text-muted-foreground truncate">{project.description}</p>}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-muted-foreground flex items-center gap-1">
            <Calendar className="w-3 h-3" />{fmtRelative(project.created_at)}
          </span>
          <Link href={`/projects/${project.id}/board`}>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs h-8">
              <LayoutDashboard className="w-3.5 h-3.5" />Board
            </Button>
          </Link>
          <Button size="sm" variant="ghost"
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => confirm(`Delete "${project.name}"? This cannot be undone.`) && deleteMutation.mutate()}>
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-border px-6 flex shrink-0">
        {TABS.map(({ id, label, Icon }) => (
          <button key={id} onClick={() => setActiveTab(id)}
            className={cn("flex items-center gap-1.5 px-4 py-3 text-xs font-medium border-b-2 transition-colors",
              activeTab === id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className={cn("flex-1 min-h-0", activeTab === "repo" ? "overflow-hidden" : "overflow-auto p-6")}>
        {activeTab === "overview"  && <OverviewTab project={project} onSave={handleSave} />}
        {activeTab === "agents"    && <AgentsTab projectId={project.id} />}
        {activeTab === "resources" && <ResourcesTab project={project} onSave={handleSave} />}
        {activeTab === "tasks"     && <TasksTab projectId={project.id} />}
        {activeTab === "logs"      && <LogsTab projectId={project.id} />}
        {activeTab === "repo"      && <RepoTab project={project} onSave={handleSave} />}
      </div>
    </div>
  );
}
