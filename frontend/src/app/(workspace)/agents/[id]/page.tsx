"use client";

import { use, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  ChevronLeft, Bot, Loader2, Save, Plus, Trash2, X,
  User, Terminal, Zap, Wrench, Network, Brain, Settings2,
  Tag, AlertCircle, MessageSquare, GitBranch, Clock, FolderKanban, FileText,
  BarChart2, Share2, Copy, Check, Globe, History, RotateCcw, ChevronDown, ChevronRight,
} from "lucide-react";
import { agentsApi, memoriesApi, skillsApi, mcpServersApi, toolsApi, providersApi, chatsApi, projectsApi } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { McpCapabilitySelector } from "@/components/shared/McpCapabilitySelector";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Agent {
  id: string;
  name: string;
  agent_type: string;
  description: string | null;
  soul: { personality?: string; expertise?: string[]; communication_style?: string };
  system_prompt: string | null;
  skills: string[];
  tools: string[];
  model_pref: string | null;
  temperature: number;
  is_active: boolean;
  is_builtin: boolean;
  env_vars: Record<string, string>;
  mcps: AgentMcpConfig[];
  max_subagents: number;
  max_concurrency: number;
}

interface AgentMcpConfig {
  server_id?: string;
  name: string;
  url: string;
  config?: Record<string, unknown>;
  allowed_tools?: string[];
}

interface Memory {
  id: string;
  agent_id: string;
  type: string;
  content: string;
  tags: string[];
  priority: number;
  created_at: string;
  updated_at: string;
}

// ── Constants ────────────────────────────────────────────────────────────────

const MEMORY_TYPES = ["fact", "instruction", "context", "example"] as const;

const MEMORY_TYPE_COLORS: Record<string, string> = {
  fact:        "bg-blue-500/10 text-blue-300 border-blue-500/20",
  instruction: "bg-purple-500/10 text-purple-300 border-purple-500/20",
  context:     "bg-cyan-500/10 text-cyan-300 border-cyan-500/20",
  example:     "bg-green-500/10 text-green-300 border-green-500/20",
};

const AGENT_TYPES = [
  "project_manager", "developer", "qa_engineer",
  "researcher", "designer", "devops", "custom",
];

const SECTIONS = [
  { id: "identity",   label: "Identity",      icon: User },
  { id: "prompt",     label: "System Prompt", icon: Terminal },
  { id: "skills",     label: "Skills",        icon: Zap },
  { id: "tools",      label: "Tools",         icon: Wrench },
  { id: "mcps",       label: "MCPs",          icon: Network },
  { id: "memory",     label: "Memory",        icon: Brain },
  { id: "env",        label: "Environment",   icon: Settings2 },
  { id: "share",      label: "Share",         icon: Share2 },
  { id: "history",    label: "History",       icon: History },
  { id: "sessions",   label: "Sessions",      icon: MessageSquare },
  { id: "analytics",  label: "Analytics",     icon: BarChart2 },
  { id: "files",      label: "Files",         icon: FileText },
] as const;

// ── Catalog skill/tool/mcp types ──────────────────────────────────────────────

interface CatalogSkill {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  is_builtin?: boolean;
}

interface CatalogTool {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  is_builtin?: boolean;
}

interface CatalogMcpTool {
  name: string;
  description: string;
  input_schema?: Record<string, unknown>;
}

interface CatalogMcp {
  id: string;
  name: string;
  url: string;
  description: string | null;
  auth_type: string | null;
  known_tools: CatalogMcpTool[];
}

type SectionId = typeof SECTIONS[number]["id"];

// ── Small helper components ───────────────────────────────────────────────────

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-6">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[180px_1fr] gap-6 items-start px-4 py-3 border-b border-border/50 last:border-0">
      <label className="text-xs text-muted-foreground pt-2 font-medium">{label}</label>
      <div className="pr-1">{children}</div>
    </div>
  );
}

function PriorityDots({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const ACTIVE_DOT_CLS = [
    "bg-sky-500 border-sky-400 shadow-[0_0_12px_rgba(14,165,233,0.35)]",
    "bg-cyan-500 border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.35)]",
    "bg-emerald-500 border-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.35)]",
    "bg-amber-500 border-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.35)]",
    "bg-red-500 border-red-400 shadow-[0_0_12px_rgba(239,68,68,0.35)]",
  ] as const;
  const ACTIVE_TEXT_CLS = [
    "text-sky-400",
    "text-cyan-400",
    "text-emerald-400",
    "text-amber-400",
    "text-red-400",
  ] as const;

  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          onClick={() => onChange(n)}
          className={cn(
            "w-3 h-3 rounded-full border transition-all",
            n <= value ? ACTIVE_DOT_CLS[n - 1] : "bg-muted/50 border-border/70"
          )}
          title={`Priority ${n}`}
        />
      ))}
      <span className={cn("text-[10px] ml-1 font-medium", ACTIVE_TEXT_CLS[Math.max(0, value - 1)] ?? "text-muted-foreground")}>
        {value}/5
      </span>
    </div>
  );
}

// ── Section components ────────────────────────────────────────────────────────

const SELECT_CLS = "h-8 w-full appearance-none rounded-md border border-input bg-background text-foreground px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring cursor-pointer [color-scheme:dark]";

function IdentitySection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [form, setForm] = useState({
    name: agent.name,
    description: agent.description ?? "",
    agent_type: agent.agent_type,
    model_pref: agent.model_pref ?? "",
    temperature: agent.temperature,
    soul: {
      personality: agent.soul?.personality ?? "",
      communication_style: agent.soul?.communication_style ?? "",
    },
  });

  const { data: chains = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ["provider-chains"],
    queryFn: () => providersApi.chains().then((r) => r.data),
  });

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div>
      <SectionHeader title="Identity" description="Core identity and personality of this agent." />
      <div className="border border-border rounded-lg overflow-hidden">
        <Field label="Name">
          <Input value={form.name} onChange={set("name")} className="h-8 text-sm" />
        </Field>
        <Field label="Description">
          <textarea
            value={form.description}
            onChange={set("description")}
            rows={2}
            className="w-full rounded-md border border-input bg-background text-foreground px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
          />
        </Field>
        <Field label="Agent type">
          <select value={form.agent_type} onChange={set("agent_type")} className={SELECT_CLS}>
            {AGENT_TYPES.map((t) => (
              <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
            ))}
          </select>
        </Field>
        <Field label="Flow preference">
          <select value={form.model_pref} onChange={set("model_pref")} className={SELECT_CLS}>
            <option value="">— No flow (use chat default) —</option>
            {chains.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Temperature">
          <div className="flex items-center gap-3">
            <input
              type="range" min={0} max={1} step={0.05}
              value={form.temperature}
              onChange={(e) => setForm((f) => ({ ...f, temperature: parseFloat(e.target.value) }))}
              className="flex-1 accent-primary"
            />
            <span className="text-xs font-mono w-8 text-right">{form.temperature.toFixed(2)}</span>
          </div>
        </Field>
        <Field label="Personality">
          <Input
            value={form.soul.personality}
            onChange={(e) => setForm((f) => ({ ...f, soul: { ...f.soul, personality: e.target.value } }))}
            placeholder="methodical, detail-oriented, prefers TypeScript…"
            className="h-8 text-sm"
          />
        </Field>
        <Field label="Communication style">
          <Input
            value={form.soul.communication_style}
            onChange={(e) => setForm((f) => ({ ...f, soul: { ...f.soul, communication_style: e.target.value } }))}
            placeholder="concise, uses bullet points, markdown-first…"
            className="h-8 text-sm"
          />
        </Field>
      </div>
      <div className="mt-4 flex justify-end">
        <Button size="sm" onClick={() => onSave({ ...form, soul: { ...agent.soul, ...form.soul } })} className="gap-2">
          <Save className="w-3.5 h-3.5" />Save Identity
        </Button>
      </div>
    </div>
  );
}

function PromptSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [prompt, setPrompt] = useState(agent.system_prompt ?? "");

  return (
    <div>
      <SectionHeader
        title="System Prompt"
        description="Instructions sent to the model at the start of every conversation. Defines the agent's role, constraints, and behaviour."
      />
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={18}
        placeholder={`You are ${agent.name}, a ${agent.agent_type.replace("_", " ")} agent...\n\nYour responsibilities include:\n- ...\n\nAlways:\n- ...`}
        className="w-full rounded-lg border border-input bg-card px-4 py-3 text-sm font-mono placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none leading-relaxed"
      />
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{prompt.length} characters</span>
        <Button size="sm" onClick={() => onSave({ system_prompt: prompt })} className="gap-2">
          <Save className="w-3.5 h-3.5" />Save Prompt
        </Button>
      </div>
    </div>
  );
}

const SKILL_CATEGORY_COLORS: Record<string, string> = {
  code:        "bg-violet-500/10 text-violet-400 border-violet-500/20",
  file:        "bg-amber-500/10 text-amber-400 border-amber-500/20",
  web:         "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  git:         "bg-green-500/10 text-green-400 border-green-500/20",
  ai:          "bg-pink-500/10 text-pink-400 border-pink-500/20",
  data:        "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  custom:      "bg-muted text-muted-foreground border-border",
};

function SkillsSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [selected, setSelected] = useState<string[]>(agent.skills ?? []);

  const { data: builtins = [] } = useQuery<CatalogSkill[]>({
    queryKey: ["skills-builtin"],
    queryFn: () => skillsApi.builtin().then((r) =>
      (r.data as CatalogSkill[]).map((b) => ({ ...b, id: `builtin:${b.key}`, is_builtin: true }))
    ),
  });
  const { data: custom = [] } = useQuery<CatalogSkill[]>({
    queryKey: ["skills"],
    queryFn: () => skillsApi.list().then((r) => r.data as CatalogSkill[]),
  });

  const allSkills = [...builtins, ...custom];

  const toggle = (key: string) =>
    setSelected((prev) => prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]);

  return (
    <div>
      <SectionHeader
        title="Skills"
        description="Select which skills from the catalog this agent can invoke."
      />
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {allSkills.length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-6 text-center">No skills in catalog</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-accent/20">
                <th className="w-8 px-3 py-2" />
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Name</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Key</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Category</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {allSkills.map((skill) => {
                const isOn = selected.includes(skill.key);
                return (
                  <tr
                    key={skill.id}
                    onClick={() => toggle(skill.key)}
                    className={cn("cursor-pointer transition-colors", isOn ? "bg-primary/5 hover:bg-primary/10" : "hover:bg-accent/30")}
                  >
                    <td className="px-3 py-2.5">
                      <div className={cn(
                        "w-4 h-4 rounded border flex items-center justify-center transition-colors",
                        isOn ? "bg-primary border-primary" : "border-border"
                      )}>
                        {isOn && <span className="text-[10px] text-primary-foreground font-bold">✓</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">{skill.name}</td>
                    <td className="px-3 py-2.5 font-mono text-muted-foreground">{skill.key}</td>
                    <td className="px-3 py-2.5">
                      <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", SKILL_CATEGORY_COLORS[skill.category] ?? SKILL_CATEGORY_COLORS.custom)}>
                        {skill.category}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground max-w-xs truncate">{skill.description ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{selected.length} skills selected</span>
        <Button size="sm" onClick={() => onSave({ skills: selected })} className="gap-2">
          <Save className="w-3.5 h-3.5" />Save Skills
        </Button>
      </div>
    </div>
  );
}

const TOOL_CATEGORY_COLORS: Record<string, string> = {
  api:         "bg-blue-500/10 text-blue-400 border-blue-500/20",
  code:        "bg-violet-500/10 text-violet-400 border-violet-500/20",
  data:        "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  file:        "bg-amber-500/10 text-amber-400 border-amber-500/20",
  integration: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  ai:          "bg-pink-500/10 text-pink-400 border-pink-500/20",
  custom:      "bg-muted text-muted-foreground border-border",
};

function ToolsSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [selected, setSelected] = useState<string[]>(agent.tools ?? []);

  useEffect(() => {
    setSelected(agent.tools ?? []);
  }, [agent.tools]);

  const { data: builtins = [], isLoading: builtinsLoading } = useQuery<CatalogTool[]>({
    queryKey: ["tools-builtin"],
    queryFn: () => toolsApi.builtin().then((r) =>
      (r.data as CatalogTool[]).map((b) => ({ ...b, id: `builtin:${b.key}`, is_builtin: true }))
    ),
  });
  const { data: custom = [], isLoading: customLoading } = useQuery<CatalogTool[]>({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list().then((r) => r.data as CatalogTool[]),
  });
  const catalogTools = [...builtins, ...custom];
  const isLoading = builtinsLoading || customLoading;

  const toggle = (key: string) =>
    setSelected((prev) => prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]);

  return (
    <div>
      <SectionHeader
        title="Tools"
        description="Select which tools from the catalog this agent has access to."
      />
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          </div>
        ) : catalogTools.length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-6 text-center">
            No tools in catalog. Add tools in the Tools section.
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-accent/20">
                <th className="w-8 px-3 py-2" />
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Name</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Key</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Category</th>
                <th className="text-left px-3 py-2 font-medium text-muted-foreground">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {catalogTools.map((tool) => {
                const isOn = selected.includes(tool.key);
                return (
                  <tr
                    key={tool.id}
                    onClick={() => toggle(tool.key)}
                    className={cn("cursor-pointer transition-colors", isOn ? "bg-primary/5 hover:bg-primary/10" : "hover:bg-accent/30")}
                  >
                    <td className="px-3 py-2.5">
                      <div className={cn(
                        "w-4 h-4 rounded border flex items-center justify-center transition-colors",
                        isOn ? "bg-primary border-primary" : "border-border"
                      )}>
                        {isOn && <span className="text-[10px] text-primary-foreground font-bold">✓</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">
                      <div className="flex items-center gap-2">
                        <span>{tool.name}</span>
                        {tool.is_builtin && (
                          <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-muted-foreground">{tool.key}</td>
                    <td className="px-3 py-2.5">
                      <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", TOOL_CATEGORY_COLORS[tool.category] ?? TOOL_CATEGORY_COLORS.custom)}>
                        {tool.category}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground max-w-xs truncate">{tool.description ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{selected.length} tools selected</span>
        <Button size="sm" onClick={() => onSave({ tools: selected })} className="gap-2">
          <Save className="w-3.5 h-3.5" />Save Tools
        </Button>
      </div>
    </div>
  );
}

function PagedToolsSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const PAGE_SIZE = 10;
  const [selected, setSelected] = useState<string[]>(agent.tools ?? []);
  const [page, setPage] = useState(1);

  useEffect(() => {
    setSelected(agent.tools ?? []);
  }, [agent.tools]);

  const { data: builtins = [], isLoading: builtinsLoading } = useQuery<CatalogTool[]>({
    queryKey: ["tools-builtin"],
    queryFn: () => toolsApi.builtin().then((r) =>
      (r.data as CatalogTool[]).map((b) => ({ ...b, id: `builtin:${b.key}`, is_builtin: true }))
    ),
  });
  const { data: custom = [], isLoading: customLoading } = useQuery<CatalogTool[]>({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list().then((r) => r.data as CatalogTool[]),
  });

  const catalogTools = [...builtins, ...custom];
  const isLoading = builtinsLoading || customLoading;
  const totalPages = Math.max(1, Math.ceil(catalogTools.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedTools = catalogTools.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [agent.id]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const toggle = (key: string) =>
    setSelected((prev) => prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]);

  return (
    <div>
      <SectionHeader
        title="Tools"
        description="Select which tools from the catalog this agent has access to."
      />
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          </div>
        ) : catalogTools.length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-6 text-center">
            No tools in catalog. Add tools in the Tools section.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] table-fixed text-xs">
              <colgroup>
                <col className="w-10" />
                <col className="w-[320px]" />
                <col className="w-[250px]" />
                <col className="w-[130px]" />
                <col />
              </colgroup>
              <thead>
                <tr className="border-b border-border bg-accent/20">
                  <th className="w-10 px-3 py-2" />
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Name</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Key</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Category</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {pagedTools.map((tool) => {
                  const isOn = selected.includes(tool.key);
                  return (
                    <tr
                      key={tool.id}
                      onClick={() => toggle(tool.key)}
                      className={cn(
                        "cursor-pointer transition-colors",
                        isOn ? "bg-primary/5 hover:bg-primary/10" : "hover:bg-accent/30"
                      )}
                    >
                      <td className="px-3 py-2.5 align-middle">
                        <div
                          className={cn(
                            "w-4 h-4 rounded border flex items-center justify-center transition-colors",
                            isOn ? "bg-primary border-primary" : "border-border"
                          )}
                        >
                          {isOn && <span className="text-[10px] text-primary-foreground font-bold">+</span>}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 align-middle font-medium text-foreground">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="truncate whitespace-nowrap">{tool.name}</span>
                          {tool.is_builtin && (
                            <Badge variant="secondary" className="text-[10px] h-4 px-1.5 shrink-0">built-in</Badge>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 align-middle font-mono text-muted-foreground truncate whitespace-nowrap">
                        {tool.key}
                      </td>
                      <td className="px-3 py-2.5 align-middle">
                        <Badge
                          variant="outline"
                          className={cn("text-[10px] h-4 px-1.5", TOOL_CATEGORY_COLORS[tool.category] ?? TOOL_CATEGORY_COLORS.custom)}
                        >
                          {tool.category}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 align-middle text-muted-foreground truncate whitespace-nowrap">
                        {tool.description ?? "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <span className="text-[11px] text-muted-foreground">{selected.length} tools selected</span>
          {catalogTools.length > PAGE_SIZE && (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground">Page {currentPage} of {totalPages}</span>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-[11px]"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
              >
                Prev
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-[11px]"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
              >
                Next
              </Button>
            </div>
          )}
        </div>
        <Button size="sm" onClick={() => onSave({ tools: selected })} className="gap-2 shrink-0">
          <Save className="w-3.5 h-3.5" />Save Tools
        </Button>
      </div>
    </div>
  );
}

function McpsSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [allowedToolsByServer, setAllowedToolsByServer] = useState<Record<string, string[]>>({});

  const { data: catalogMcps = [], isLoading } = useQuery<CatalogMcp[]>({
    queryKey: ["mcp-servers"],
    queryFn: () => mcpServersApi.list().then((r) => r.data as CatalogMcp[]),
  });

  useEffect(() => {
    const nextSelectedIds: string[] = [];
    const nextExpandedIds: string[] = [];
    const nextAllowedTools: Record<string, string[]> = {};

    for (const mcp of catalogMcps) {
      const saved = (agent.mcps ?? []).find((entry) =>
        entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url
      );

      if (!saved) continue;

      nextSelectedIds.push(mcp.id);

      const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
      if (knownToolNames.length === 0) {
        if (Array.isArray(saved.allowed_tools)) {
          nextAllowedTools[mcp.id] = saved.allowed_tools;
        }
        continue;
      }

      const allowedTools = Array.isArray(saved.allowed_tools)
        ? saved.allowed_tools.filter((tool) => knownToolNames.includes(tool))
        : knownToolNames;

      nextAllowedTools[mcp.id] = allowedTools;

      if (allowedTools.length > 0 && allowedTools.length < knownToolNames.length) {
        nextExpandedIds.push(mcp.id);
      }
    }

    setSelectedIds(nextSelectedIds);
    setExpandedIds(nextExpandedIds);
    setAllowedToolsByServer(nextAllowedTools);
  }, [agent.mcps, catalogMcps]);

  const toggleServer = (mcp: CatalogMcp) => {
    const isSelected = selectedIds.includes(mcp.id);
    setSelectedIds((prev) =>
      isSelected ? prev.filter((id) => id !== mcp.id) : [...prev, mcp.id]
    );

    if (!isSelected) {
      const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
      if (knownToolNames.length > 0) {
        setAllowedToolsByServer((prev) =>
          prev[mcp.id] ? prev : { ...prev, [mcp.id]: knownToolNames }
        );
      }
    }
  };

  const toggleExpanded = (mcpId: string) =>
    setExpandedIds((prev) =>
      prev.includes(mcpId) ? prev.filter((id) => id !== mcpId) : [...prev, mcpId]
    );

  const setAllTools = (mcp: CatalogMcp) =>
    setAllowedToolsByServer((prev) => ({
      ...prev,
      [mcp.id]: (mcp.known_tools ?? []).map((tool) => tool.name),
    }));

  const clearAllTools = (mcp: CatalogMcp) =>
    setAllowedToolsByServer((prev) => ({
      ...prev,
      [mcp.id]: [],
    }));

  const toggleTool = (mcp: CatalogMcp, toolName: string) => {
    const fallback = (mcp.known_tools ?? []).map((tool) => tool.name);
    setAllowedToolsByServer((prev) => {
      const current = prev[mcp.id] ?? fallback;
      const next = current.includes(toolName)
        ? current.filter((name) => name !== toolName)
        : [...current, toolName];
      return { ...prev, [mcp.id]: next };
    });
  };

  const selectedMcps = catalogMcps
    .filter((m) => selectedIds.includes(m.id))
    .map((m) => {
      const knownToolNames = (m.known_tools ?? []).map((tool) => tool.name);
      const payload: AgentMcpConfig = {
        server_id: m.id,
        name: m.name,
        url: m.url,
      };

      if (knownToolNames.length > 0) {
        const allowedTools = (allowedToolsByServer[m.id] ?? knownToolNames)
          .filter((tool) => knownToolNames.includes(tool));

        if (allowedTools.length !== knownToolNames.length) {
          payload.allowed_tools = allowedTools;
        }
      }

      return payload;
    });

  const handleSave = () => {
    onSave({ mcps: selectedMcps });
  };

  return (
    <div>
      <SectionHeader
        title="MCP Servers"
        description="Select which MCP servers from the catalog this agent can call. Servers are configured in the MCP Servers section."
      />
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          </div>
        ) : catalogMcps.length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-6 text-center">
            No MCP servers in catalog. Add servers in the MCP Servers section.
          </p>
        ) : (false && (
          <div className="divide-y divide-border">
            {catalogMcps.map((mcp) => {
              const isOn = selectedIds.includes(mcp.id);
              const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
              const selectedToolNames = allowedToolsByServer[mcp.id] ?? knownToolNames;
              const selectedToolCount = selectedToolNames.filter((tool) => knownToolNames.includes(tool)).length;
              const isExpanded = expandedIds.includes(mcp.id);
              const hasDiscoveredTools = knownToolNames.length > 0;

              return (
                <div key={mcp.id}>
                  <div
                    onClick={() => toggleServer(mcp)}
                    className={cn(
                      "flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors",
                      isOn ? "bg-primary/5 hover:bg-primary/10" : "hover:bg-accent/30"
                    )}
                  >
                    <div className={cn(
                      "w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors",
                      isOn ? "bg-primary border-primary" : "border-border"
                    )}>
                      {isOn && <span className="text-[10px] text-primary-foreground font-bold">✓</span>}
                    </div>
                    <Network className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="text-xs font-medium text-foreground">{mcp.name}</div>
                        {hasDiscoveredTools && (
                          <span className="text-[10px] text-muted-foreground">
                            {isOn
                              ? (selectedToolCount === knownToolNames.length
                                ? `All ${knownToolNames.length} tools`
                                : `${selectedToolCount}/${knownToolNames.length} tools`)
                              : `${knownToolNames.length} tools discovered`}
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-muted-foreground font-mono truncate">{mcp.url}</div>
                    </div>
                    {mcp.description && (
                      <span className="text-[11px] text-muted-foreground truncate max-w-[160px]">{mcp.description}</span>
                    )}
                    {mcp.auth_type && mcp.auth_type !== "none" && (
                      <Badge variant="outline" className="text-[10px] h-4 px-1.5 shrink-0">
                        {mcp.auth_type}
                      </Badge>
                    )}
                    {isOn && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpanded(mcp.id);
                        }}
                        className="text-[10px] text-primary hover:text-primary/80 shrink-0"
                      >
                        {isExpanded ? "Hide details" : hasDiscoveredTools ? "Choose tools" : "View details"}
                      </button>
                    )}
                  </div>
                  {isOn && isExpanded && (
                    <div className="px-4 pb-4 bg-primary/5 border-t border-primary/10">
                      {hasDiscoveredTools ? (
                        <div className="pt-3 space-y-3">
                          <div className="flex items-center justify-between">
                            <p className="text-[11px] text-muted-foreground">
                              Limit this MCP to specific functions for this agent.
                            </p>
                            <div className="flex items-center gap-2">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setAllTools(mcp);
                                }}
                                className="text-[10px] text-muted-foreground hover:text-foreground"
                              >
                                Select all
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  clearAllTools(mcp);
                                }}
                                className="text-[10px] text-muted-foreground hover:text-foreground"
                              >
                                Clear
                              </button>
                            </div>
                          </div>
                          <div className="border border-border rounded-lg overflow-hidden bg-card">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-border bg-accent/20">
                                  <th className="w-8 px-3 py-2" />
                                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Tool</th>
                                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Description</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-border">
                                {mcp.known_tools.map((tool) => {
                                  const toolOn = selectedToolNames.includes(tool.name);
                                  return (
                                    <tr
                                      key={tool.name}
                                      onClick={() => toggleTool(mcp, tool.name)}
                                      className={cn(
                                        "cursor-pointer transition-colors",
                                        toolOn ? "bg-primary/5 hover:bg-primary/10" : "hover:bg-accent/30"
                                      )}
                                    >
                                      <td className="px-3 py-2.5">
                                        <div className={cn(
                                          "w-4 h-4 rounded border flex items-center justify-center transition-colors",
                                          toolOn ? "bg-primary border-primary" : "border-border"
                                        )}>
                                          {toolOn && <span className="text-[10px] text-primary-foreground font-bold">✓</span>}
                                        </div>
                                      </td>
                                      <td className="px-3 py-2.5 font-mono text-foreground">{tool.name}</td>
                                      <td className="px-3 py-2.5 text-muted-foreground max-w-lg truncate">{tool.description || "—"}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ) : (
                        <div className="pt-3 flex items-start gap-2 text-[11px] text-muted-foreground">
                          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                          <p>
                            No tools discovered for this server yet. Fetch them from the MCP Servers page before restricting
                            access per function.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
        {!isLoading && catalogMcps.length > 0 && (
          <McpCapabilitySelector
            catalogMcps={catalogMcps}
            selectedMcps={selectedMcps}
            onToggleMcp={(mcp) => toggleServer(mcp as CatalogMcp)}
            onSetAllowedTools={(mcp, allowedTools) =>
              setAllowedToolsByServer((prev) => ({ ...prev, [mcp.id]: allowedTools }))
            }
            emptyText="No MCP servers in catalog. Add servers in the MCP Servers section."
            footerText="Select which MCP servers from the catalog this agent can call. If a server has discovered tools, you can restrict it to only some of them."
          />
        )}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{selectedIds.length} servers selected</span>
        <Button size="sm" onClick={handleSave} className="gap-2">
          <Save className="w-3.5 h-3.5" />Save MCPs
        </Button>
      </div>
    </div>
  );
}

function MemorySection({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const [newContent, setNewContent] = useState("");
  const [newType, setNewType] = useState<typeof MEMORY_TYPES[number]>("fact");
  const [newPriority, setNewPriority] = useState(3);
  const [newTag, setNewTag] = useState("");
  const [newTags, setNewTags] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  const { data: memories = [], isLoading } = useQuery({
    queryKey: ["memories", agentId],
    queryFn: () => memoriesApi.list(agentId).then((r) => r.data as Memory[]),
  });

  const createMem = useMutation({
    mutationFn: () => memoriesApi.create(agentId, { type: newType, content: newContent, tags: newTags, priority: newPriority }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories", agentId] });
      setNewContent(""); setNewTags([]); setNewTag(""); setNewPriority(3);
      toast.success("Memory added");
    },
    onError: () => toast.error("Failed to add memory"),
  });

  const updateMem = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      memoriesApi.update(agentId, id, { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories", agentId] });
      setEditingId(null);
    },
    onError: () => toast.error("Failed to update"),
  });

  const deleteMem = useMutation({
    mutationFn: (id: string) => memoriesApi.delete(agentId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories", agentId] }),
    onError: () => toast.error("Failed to delete"),
  });

  const grouped = memories.reduce<Record<string, Memory[]>>((acc, m) => {
    if (!acc[m.type]) acc[m.type] = [];
    acc[m.type].push(m);
    return acc;
  }, {});

  return (
    <div>
      <SectionHeader
        title="Agent Memory"
        description="Persistent facts, instructions, and context injected into every conversation. Higher priority entries appear first."
      />

      {/* New memory form */}
      <div className="bg-card border border-border rounded-lg p-4 mb-4 space-y-3">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Add memory entry</p>
        <div className="flex items-center gap-2">
          <select
            value={newType}
            onChange={(e) => setNewType(e.target.value as typeof newType)}
            className={cn(SELECT_CLS, "w-auto min-w-28 px-2 text-xs")}
          >
            {MEMORY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">Priority:</span>
            <PriorityDots value={newPriority} onChange={setNewPriority} />
          </div>
        </div>
        <textarea
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          rows={3}
          placeholder={
            newType === "fact" ? "The project uses PostgreSQL 16 and Redis 7." :
            newType === "instruction" ? "Always respond in the same language as the user." :
            newType === "context" ? "This agent works within the Nexora platform." :
            "User: How do I create an agent?\nAssistant: Navigate to /agents and click New Agent."
          }
          className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
        />
        <div className="flex items-center gap-2">
          <div className="flex flex-wrap gap-1 flex-1">
            {newTags.map((tag) => (
              <span key={tag} className="flex items-center gap-0.5 text-[10px] bg-accent px-1.5 py-0.5 rounded">
                {tag}
                <button onClick={() => setNewTags((prev) => prev.filter((t) => t !== tag))}>
                  <X className="w-2.5 h-2.5" />
                </button>
              </span>
            ))}
            <Input
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTag.trim()) {
                  setNewTags((prev) => [...prev, newTag.trim()]);
                  setNewTag("");
                }
              }}
              placeholder="tag…"
              className="h-6 text-xs w-24 px-2"
            />
          </div>
          <Button
            size="sm"
            onClick={() => createMem.mutate()}
            disabled={!newContent.trim() || createMem.isPending}
            className="gap-1.5 shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />Add
          </Button>
        </div>
      </div>

      {/* Memory list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : memories.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground text-xs border border-dashed border-border rounded-lg">
          No memory entries yet. Add one above.
        </div>
      ) : (
        <div className="space-y-4">
          {MEMORY_TYPES.filter((t) => grouped[t]?.length).map((type) => (
            <div key={type}>
              <div className="flex items-center gap-2 mb-2">
                <span className={cn("text-[10px] px-2 py-0.5 rounded border font-semibold uppercase", MEMORY_TYPE_COLORS[type])}>
                  {type}
                </span>
                <span className="text-[10px] text-muted-foreground">{grouped[type].length}</span>
              </div>
              <div className="bg-card border border-border rounded-lg divide-y divide-border overflow-hidden">
                {grouped[type].map((m) => (
                  <div key={m.id} className="group p-3 hover:bg-accent/20 transition-colors">
                    <div className="flex items-start gap-2">
                      <PriorityDots value={m.priority} onChange={() => {}} />
                      <div className="flex-1 min-w-0">
                        {editingId === m.id ? (
                          <div className="space-y-2">
                            <textarea
                              value={editContent}
                              onChange={(e) => setEditContent(e.target.value)}
                              rows={3}
                              className="w-full rounded border border-input bg-transparent px-2 py-1.5 text-xs resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            />
                            <div className="flex gap-1">
                              <Button size="sm" className="h-6 text-xs" onClick={() => updateMem.mutate({ id: m.id, content: editContent })}>
                                Save
                              </Button>
                              <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditingId(null)}>
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <p
                            className="text-xs text-foreground cursor-pointer hover:text-primary transition-colors leading-relaxed"
                            onClick={() => { setEditingId(m.id); setEditContent(m.content); }}
                          >
                            {m.content}
                          </p>
                        )}
                        {m.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {m.tags.map((tag) => (
                              <span key={tag} className="text-[10px] bg-accent px-1.5 py-0.5 rounded text-muted-foreground flex items-center gap-0.5">
                                <Tag className="w-2.5 h-2.5" />
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => deleteMem.mutate(m.id)}
                        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all shrink-0"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EnvironmentSection({ agent, onSave }: { agent: Agent; onSave: (data: Partial<Agent>) => void }) {
  const [envVars, setEnvVars] = useState<Record<string, string>>(agent.env_vars ?? {});
  const [maxSubagents, setMaxSubagents] = useState(agent.max_subagents);
  const [maxConcurrency, setMaxConcurrency] = useState(agent.max_concurrency);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");

  const addVar = () => {
    if (!newKey.trim()) return;
    setEnvVars((prev) => ({ ...prev, [newKey.trim()]: newVal }));
    setNewKey(""); setNewVal("");
  };

  return (
    <div>
      <SectionHeader
        title="Environment"
        description="Environment variables injected when the agent runs CLI tools. Also controls concurrency limits for sub-agent spawning."
      />

      {/* Concurrency */}
      <div className="bg-card border border-border rounded-lg p-4 mb-4">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Concurrency Limits</p>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Max sub-agents</label>
            <Input
              type="number" min={1} max={20}
              value={maxSubagents}
              onChange={(e) => setMaxSubagents(parseInt(e.target.value) || 5)}
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Max concurrency</label>
            <Input
              type="number" min={1} max={10}
              value={maxConcurrency}
              onChange={(e) => setMaxConcurrency(parseInt(e.target.value) || 2)}
              className="h-8 text-sm"
            />
          </div>
        </div>
      </div>

      {/* Env vars */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border bg-accent/20">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Environment Variables</p>
        </div>
        {Object.keys(envVars).length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-4 text-center">No environment variables</p>
        ) : (
          <div className="divide-y divide-border">
            {Object.entries(envVars).map(([k, v]) => (
              <div key={k} className="flex items-center gap-3 px-4 py-2.5 group font-mono text-xs">
                <span className="text-foreground font-semibold">{k}</span>
                <span className="text-muted-foreground">=</span>
                <span className="flex-1 text-muted-foreground truncate">{v}</span>
                <button
                  onClick={() => setEnvVars((prev) => { const e = { ...prev }; delete e[k]; return e; })}
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 p-3 border-t border-border bg-accent/20">
          <Input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="KEY" className="h-8 text-xs font-mono w-32" />
          <Input
            value={newVal}
            onChange={(e) => setNewVal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addVar()}
            placeholder="value"
            className="h-8 text-xs font-mono flex-1"
          />
          <Button size="sm" variant="outline" onClick={addVar} disabled={!newKey.trim()}>Add</Button>
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          onClick={() => onSave({ env_vars: envVars, max_subagents: maxSubagents, max_concurrency: maxConcurrency })}
          className="gap-2"
        >
          <Save className="w-3.5 h-3.5" />Save Environment
        </Button>
      </div>
    </div>
  );
}

// ── Share section ─────────────────────────────────────────────────────────────

function ShareSection({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [embedCopied, setEmbedCopied] = useState(false);

  const { data: shareData, isLoading } = useQuery({
    queryKey: ["agent-share", agentId],
    queryFn: () => agentsApi.getShare(agentId).then((r) => r.data),
    retry: (count, err: unknown) => {
      const e = err as { response?: { status?: number } };
      return e?.response?.status !== 404 && count < 2;
    },
  });

  const enable = useMutation({
    mutationFn: () => agentsApi.enableShare(agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-share", agentId] });
      toast.success("Sharing enabled");
    },
    onError: () => toast.error("Failed to enable sharing"),
  });

  const disable = useMutation({
    mutationFn: () => agentsApi.disableShare(agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-share", agentId] });
      toast.success("Sharing disabled");
    },
    onError: () => toast.error("Failed to disable sharing"),
  });

  const copyUrl = () => {
    if (!shareData?.share_url) return;
    navigator.clipboard.writeText(shareData.share_url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const embedSnippet = shareData?.share_url
    ? `<iframe\n  src="${shareData.share_url}"\n  width="400"\n  height="600"\n  frameborder="0"\n  allow="clipboard-write"\n  title="Chat with agent"\n></iframe>`
    : "";

  const copyEmbed = () => {
    if (!embedSnippet) return;
    navigator.clipboard.writeText(embedSnippet).then(() => {
      setEmbedCopied(true);
      setTimeout(() => setEmbedCopied(false), 2000);
    });
  };

  const isEnabled = shareData?.share_enabled ?? false;
  const shareUrl = shareData?.share_url ?? "";

  return (
    <div>
      <SectionHeader
        title="Share"
        description="Generate a public link so anyone can chat with this agent without logging in. The link expires when you disable sharing."
      />

      <div className="border border-border rounded-lg overflow-hidden">
        {/* Toggle row */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Public sharing</p>
              <p className="text-xs text-muted-foreground">
                {isEnabled ? "Anyone with the link can chat with this agent" : "Sharing is disabled"}
              </p>
            </div>
          </div>
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          ) : (
            <button
              onClick={() => isEnabled ? disable.mutate() : enable.mutate()}
              disabled={enable.isPending || disable.isPending}
              className={cn(
                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none disabled:opacity-50",
                isEnabled ? "bg-primary" : "bg-muted"
              )}
            >
              <span
                className={cn(
                  "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform",
                  isEnabled ? "translate-x-4" : "translate-x-0"
                )}
              />
            </button>
          )}
        </div>

        {/* Share URL */}
        {isEnabled && shareUrl && (
          <>
            <div className="px-4 py-3 border-b border-border">
              <p className="text-xs text-muted-foreground font-medium mb-2">Share URL</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs font-mono bg-muted/50 rounded px-3 py-2 truncate text-foreground">
                  {shareUrl}
                </code>
                <Button size="sm" variant="outline" onClick={copyUrl} className="gap-1.5 shrink-0 h-8">
                  {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>

            {/* Embed snippet */}
            <div className="px-4 py-3">
              <p className="text-xs text-muted-foreground font-medium mb-2">Embed snippet</p>
              <p className="text-xs text-muted-foreground mb-2">
                Paste this into any HTML page to embed a chat widget.
              </p>
              <div className="relative">
                <pre className="text-xs font-mono bg-muted/50 rounded px-3 py-2 overflow-x-auto text-foreground">
                  {embedSnippet}
                </pre>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={copyEmbed}
                  className="absolute top-2 right-2 gap-1.5 h-7 text-xs"
                >
                  {embedCopied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                  {embedCopied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {isEnabled && shareUrl && (
        <p className="mt-3 text-xs text-muted-foreground">
          Rate limited to 10 requests per minute per visitor IP.
        </p>
      )}
    </div>
  );
}


// ── Sessions section ──────────────────────────────────────────────────────────

interface ChatSession {
  id: string;
  title: string;
  agent_id: string | null;
  project_id: string | null;
  updated_at: string;
  created_at: string;
}

function SessionsSection({ agentId, agentName }: { agentId: string; agentName: string }) {
  const router = useRouter();
  const qc = useQueryClient();

  const { data: sessions = [], isLoading } = useQuery<ChatSession[]>({
    queryKey: ["chats", { agent_id: agentId }],
    queryFn: () => chatsApi.list({ agent_id: agentId }).then((r) => r.data),
  });

  const { data: projects = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then((r) => r.data),
  });
  const projectMap = Object.fromEntries(projects.map((p) => [p.id, p.name]));

  const createSession = useMutation({
    mutationFn: () => chatsApi.create({ title: `Session with ${agentName}`, agent_id: agentId }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      router.push(`/chat/${res.data.id}`);
    },
  });

  return (
    <div>
      <SectionHeader
        title="Sessions"
        description={`Conversations that used ${agentName} as their active agent.`}
      />

      {/* New session button */}
      <div className="mb-6">
        <Button
          onClick={() => createSession.mutate()}
          disabled={createSession.isPending}
          className="gap-2"
        >
          <Plus className="w-3.5 h-3.5" />
          New Session with {agentName}
        </Button>
      </div>

      {/* Session list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-center border border-dashed border-border rounded-lg">
          <MessageSquare className="w-8 h-8 text-muted-foreground/40" />
          <div>
            <p className="text-sm font-medium text-muted-foreground">No sessions yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Start a new session above or open a chat with this agent selected.
            </p>
          </div>
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="divide-y divide-border">
            {sessions.map((session) => (
              <div
                key={session.id}
                className="flex items-center gap-4 px-4 py-3 hover:bg-accent/30 transition-colors group"
              >
                {/* Icon */}
                <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <GitBranch className="w-3.5 h-3.5 text-primary" />
                </div>

                {/* Title + meta */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{session.title || "Untitled Session"}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    {session.project_id && projectMap[session.project_id] && (
                      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                        <FolderKanban className="w-2.5 h-2.5" />
                        {projectMap[session.project_id]}
                      </span>
                    )}
                    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Clock className="w-2.5 h-2.5" />
                      {formatDate(session.updated_at || session.created_at)}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs gap-1.5"
                    onClick={() => router.push(`/chat/${session.id}`)}
                  >
                    <MessageSquare className="w-3 h-3" />
                    Open
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Files section (builtin agents only) ──────────────────────────────────────

function FilesSection({ agent }: { agent: Agent }) {
  const key = agent.name.toLowerCase().replace(/\s+/g, "_");

  const { data, isLoading } = useQuery<{ files: Record<string, string>; name: string }>({
    queryKey: ["agent-builtin-files", key],
    queryFn: () => agentsApi.builtinFiles(key).then((r) => r.data),
    enabled: agent.is_builtin,
  });

  if (!agent.is_builtin) {
    return (
      <div>
        <SectionHeader title="Files" description="Source files for this agent." />
        <div className="flex flex-col items-center justify-center py-12 gap-2 border border-dashed border-border rounded-lg">
          <FileText className="w-8 h-8 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Custom agents don't have seed files.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div>
        <SectionHeader title="Files" description="Source files for this agent." />
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  const files = data?.files ?? {};

  return (
    <div>
      <SectionHeader title="Files" description={`Seed files for the built-in ${agent.name} agent. Read-only.`} />
      {Object.keys(files).length === 0 ? (
        <div className="text-center py-8 text-muted-foreground text-xs border border-dashed border-border rounded-lg">
          No seed files found for this agent.
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(files).map(([filename, content]) => (
            <div key={filename} className="border border-border rounded-lg overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 bg-accent/30 border-b border-border">
                <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-xs font-mono font-medium text-foreground">{filename}</span>
              </div>
              <pre className="px-4 py-3 text-xs font-mono text-muted-foreground whitespace-pre-wrap overflow-auto max-h-96 leading-relaxed bg-card">
                {content}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Analytics section ─────────────────────────────────────────────────────────

interface AgentAnalytics {
  agent_id: string;
  days: number;
  total_chats: number;
  total_messages: number;
  total_tokens: number;
  error_count: number;
  daily_messages: { date: string; count: number }[];
}

const DAY_OPTIONS = [7, 30, 90] as const;

function AnalyticsSection({ agentId }: { agentId: string }) {
  const [days, setDays] = useState<7 | 30 | 90>(30);

  const { data, isLoading, error } = useQuery<AgentAnalytics>({
    queryKey: ["agent-analytics", agentId, days],
    queryFn: () => agentsApi.analytics(agentId, days).then((r) => r.data as AgentAnalytics),
  });

  const maxCount = Math.max(...(data?.daily_messages ?? []).map((d) => d.count), 1);

  return (
    <div>
      <SectionHeader
        title="Analytics"
        description="Message activity, token usage, and error counts for this agent."
      />

      {/* Days selector */}
      <div className="flex items-center gap-1 mb-6">
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={cn(
              "px-3 py-1 text-xs rounded-md border transition-colors",
              days === d
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
            )}
          >
            {d}d
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : error || !data ? (
        <div className="flex flex-col items-center justify-center py-12 gap-2 border border-dashed border-border rounded-lg">
          <AlertCircle className="w-6 h-6 text-muted-foreground/50" />
          <p className="text-xs text-muted-foreground">Failed to load analytics</p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Total Chats",    value: data.total_chats.toLocaleString() },
              { label: "Total Messages", value: data.total_messages.toLocaleString() },
              { label: "Total Tokens",   value: data.total_tokens.toLocaleString() },
              { label: `Errors (${days}d)`, value: data.error_count.toLocaleString() },
            ].map(({ label, value }) => (
              <div key={label} className="bg-card border border-border rounded-lg px-4 py-3">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">{label}</p>
                <p className="text-xl font-semibold mt-1">{value}</p>
              </div>
            ))}
          </div>

          {/* Daily messages bar chart */}
          <div className="bg-card border border-border rounded-lg p-4">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-4">
              Messages per day — last {days} days
            </p>
            {data.daily_messages.length === 0 ? (
              <div className="flex items-center justify-center h-20 text-xs text-muted-foreground">
                No messages in this period
              </div>
            ) : (
              <div className="flex items-end gap-0.5 h-24 w-full">
                {data.daily_messages.map((d) => (
                  <div
                    key={d.date}
                    title={`${d.date}: ${d.count} message${d.count !== 1 ? "s" : ""}`}
                    className="flex-1 bg-indigo-500 hover:bg-indigo-400 rounded-t transition-colors min-h-[2px]"
                    style={{ height: `${(d.count / maxCount) * 100}%` }}
                  />
                ))}
              </div>
            )}
            {data.daily_messages.length > 0 && (
              <div className="flex justify-between mt-1.5">
                <span className="text-[10px] text-muted-foreground">{data.daily_messages[0].date}</span>
                <span className="text-[10px] text-muted-foreground">{data.daily_messages[data.daily_messages.length - 1].date}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── History section ──────────────────────────────────────────────────────────

interface AgentVersionSummary {
  id: string;
  version_number: number;
  created_at: string;
  created_by_name: string | null;
}

interface AgentVersionDetail extends AgentVersionSummary {
  snapshot: Record<string, unknown>;
}

const SNAPSHOT_FIELD_LABELS: Record<string, string> = {
  name: "Name",
  agent_type: "Agent Type",
  description: "Description",
  soul: "Soul / Personality",
  system_prompt: "System Prompt",
  skills: "Skills",
  tools: "Tools",
  mcps: "MCP Servers",
  env_vars: "Environment Variables",
  model_pref: "Model Preference",
  temperature: "Temperature",
  max_tokens: "Max Tokens",
  max_subagents: "Max Sub-agents",
  max_concurrency: "Max Concurrency",
  flow_config: "Flow Config",
  is_active: "Active",
};

function renderSnapshotValue(key: string, val: unknown): React.ReactNode {
  if (val === null || val === undefined) return <span className="text-muted-foreground italic">—</span>;
  if (typeof val === "boolean") return <span>{val ? "Yes" : "No"}</span>;
  if (typeof val === "number") return <span className="font-mono">{val}</span>;
  if (Array.isArray(val)) {
    if (val.length === 0) return <span className="text-muted-foreground italic">None</span>;
    return (
      <div className="flex flex-wrap gap-1">
        {val.map((item, i) => (
          <span key={i} className="text-[10px] bg-accent px-1.5 py-0.5 rounded font-mono">
            {typeof item === "string" ? item : JSON.stringify(item)}
          </span>
        ))}
      </div>
    );
  }
  if (typeof val === "object") {
    const entries = Object.entries(val as Record<string, unknown>).filter(([, v]) => v !== null && v !== undefined && v !== "");
    if (entries.length === 0) return <span className="text-muted-foreground italic">Empty</span>;
    if (key === "soul") {
      return (
        <div className="space-y-1">
          {entries.map(([k, v]) => (
            <div key={k} className="text-xs">
              <span className="text-muted-foreground capitalize">{k.replace(/_/g, " ")}: </span>
              <span>{typeof v === "string" ? v : JSON.stringify(v)}</span>
            </div>
          ))}
        </div>
      );
    }
    return (
      <pre className="text-xs font-mono bg-muted/40 rounded px-2 py-1.5 overflow-auto max-h-32 whitespace-pre-wrap">
        {JSON.stringify(val, null, 2)}
      </pre>
    );
  }
  if (typeof val === "string") {
    if (val.length > 200) {
      return (
        <pre className="text-xs font-mono bg-muted/40 rounded px-2 py-1.5 overflow-auto max-h-40 whitespace-pre-wrap leading-relaxed">
          {val}
        </pre>
      );
    }
    return <span className="text-sm">{val}</span>;
  }
  return <span>{String(val)}</span>;
}

function VersionDetailPanel({
  version,
  agentId,
  onRevert,
  onClose,
}: {
  version: AgentVersionDetail;
  agentId: string;
  onRevert: () => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();

  const revert = useMutation({
    mutationFn: () => agentsApi.revertToVersion(agentId, version.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent", agentId] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["agent-versions", agentId] });
      toast.success(`Reverted to version ${version.version_number}`);
      onRevert();
    },
    onError: () => toast.error("Revert failed"),
  });

  const snap = version.snapshot;
  const displayFields = Object.keys(SNAPSHOT_FIELD_LABELS).filter(
    (k) => snap[k] !== undefined
  );

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 bg-accent/30 border-b border-border">
        <div className="flex items-center gap-2">
          <History className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">
            Version {version.version_number}
          </span>
          <span className="text-[10px] text-muted-foreground">
            {formatDate(version.created_at)}
            {version.created_by_name ? ` · by ${version.created_by_name}` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs gap-1.5"
            onClick={() => {
              if (confirm(`Revert agent to version ${version.version_number}? This will create a new version with the restored config.`)) {
                revert.mutate();
              }
            }}
            disabled={revert.isPending}
          >
            {revert.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RotateCcw className="w-3 h-3" />
            )}
            Revert to this version
          </Button>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Snapshot fields */}
      <div className="divide-y divide-border">
        {displayFields.map((key) => (
          <div key={key} className="grid grid-cols-[180px_1fr] gap-4 items-start px-4 py-3">
            <span className="text-xs text-muted-foreground pt-0.5 font-medium">
              {SNAPSHOT_FIELD_LABELS[key] ?? key}
            </span>
            <div className="text-xs text-foreground min-w-0">
              {renderSnapshotValue(key, snap[key])}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HistorySection({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const { data: versions = [], isLoading } = useQuery<AgentVersionSummary[]>({
    queryKey: ["agent-versions", agentId],
    queryFn: () => agentsApi.listVersions(agentId).then((r) => r.data as AgentVersionSummary[]),
  });

  const { data: selectedVersion, isLoading: loadingDetail } = useQuery<AgentVersionDetail>({
    queryKey: ["agent-version-detail", agentId, selectedVersionId],
    queryFn: () =>
      agentsApi.getVersion(agentId, selectedVersionId!).then((r) => r.data as AgentVersionDetail),
    enabled: !!selectedVersionId,
  });

  const handleSelect = (vId: string) => {
    setSelectedVersionId((prev) => (prev === vId ? null : vId));
  };

  return (
    <div>
      <SectionHeader
        title="Version History"
        description="Every save creates a snapshot of the agent configuration. Click any version to inspect or revert to it."
      />

      {isLoading ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : versions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-center border border-dashed border-border rounded-lg">
          <History className="w-8 h-8 text-muted-foreground/40" />
          <div>
            <p className="text-sm font-medium text-muted-foreground">No versions yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Save any change to the agent to create the first snapshot.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Version list */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <div className="divide-y divide-border">
              {versions.map((v, idx) => {
                const isSelected = selectedVersionId === v.id;
                const isLatest = idx === 0;
                return (
                  <div key={v.id}>
                    <button
                      onClick={() => handleSelect(v.id)}
                      className={cn(
                        "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors",
                        isSelected
                          ? "bg-primary/5 hover:bg-primary/10"
                          : "hover:bg-accent/30"
                      )}
                    >
                      {/* Expand arrow */}
                      {isSelected ? (
                        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      )}

                      {/* Version badge */}
                      <div className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-semibold",
                        isLatest
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground"
                      )}>
                        v{v.version_number}
                      </div>

                      {/* Meta */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-foreground">
                            Version {v.version_number}
                          </span>
                          {isLatest && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">
                              latest
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                            <Clock className="w-2.5 h-2.5" />
                            {formatDate(v.created_at)}
                          </span>
                          {v.created_by_name && (
                            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                              <User className="w-2.5 h-2.5" />
                              {v.created_by_name}
                            </span>
                          )}
                        </div>
                      </div>
                    </button>

                    {/* Inline detail panel */}
                    {isSelected && (
                      <div className="px-4 pb-4 border-t border-border bg-accent/10">
                        {loadingDetail ? (
                          <div className="flex items-center justify-center py-6">
                            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                          </div>
                        ) : selectedVersion ? (
                          <div className="pt-3">
                            <VersionDetailPanel
                              version={selectedVersion}
                              agentId={agentId}
                              onRevert={() => setSelectedVersionId(null)}
                              onClose={() => setSelectedVersionId(null)}
                            />
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AgentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: agentId } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const [activeSection, setActiveSection] = useState<SectionId>("identity");

  const { data: agent, isLoading, error } = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => agentsApi.get(agentId).then((r) => r.data as Agent),
  });

  const update = useMutation({
    mutationFn: (data: Partial<Agent>) => agentsApi.update(agentId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent", agentId] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  const deleteAgent = useMutation({
    mutationFn: () => agentsApi.delete(agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent deleted");
      router.push("/agents");
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <AlertCircle className="w-8 h-8 text-destructive" />
        <p className="text-sm text-muted-foreground">Agent not found</p>
        <Button variant="outline" size="sm" onClick={() => router.push("/agents")}>
          Back to agents
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0">
        <button
          onClick={() => router.push("/agents")}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Bot className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-semibold">{agent.name}</h1>
          <p className="text-[10px] text-muted-foreground capitalize">{agent.agent_type.replace("_", " ")}</p>
        </div>
        <div className="flex items-center gap-2">
          {agent.is_builtin && (
            <Badge variant="secondary" className="text-[10px] px-2 py-0.5">built-in</Badge>
          )}
          <span className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium",
            agent.is_active
              ? "bg-green-500/10 text-green-400 border-green-500/20"
              : "bg-muted text-muted-foreground border-border"
          )}>
            {agent.is_active ? "Active" : "Inactive"}
          </span>
          {!agent.is_builtin && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm(`Delete "${agent.name}"? This cannot be undone.`)) deleteAgent.mutate();
              }}
              className="gap-1.5 text-destructive hover:text-destructive hover:bg-destructive/10 h-7 text-xs"
            >
              <Trash2 className="w-3.5 h-3.5" />Delete
            </Button>
          )}
        </div>
      </div>

      {/* Section nav (horizontal tabs) */}
      <div className="flex items-center gap-0 border-b border-border px-6 shrink-0 overflow-x-auto">
        {SECTIONS.filter(({ id }) => id !== "files" || agent.is_builtin).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveSection(id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap",
              activeSection === id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Section content */}
      <div className={cn(
        "flex-1 overflow-y-auto p-6 w-full mx-auto",
        activeSection === "tools"     ? "max-w-6xl" :
        activeSection === "mcps"      ? "max-w-5xl" :
        activeSection === "sessions"  ? "max-w-4xl" :
        activeSection === "analytics" ? "max-w-4xl" :
        activeSection === "history"   ? "max-w-4xl" :
        activeSection === "share"     ? "max-w-2xl" : "max-w-3xl"
      )}>
        {activeSection === "identity"   && <IdentitySection     agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "prompt"     && <PromptSection       agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "skills"     && <SkillsSection       agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "tools"      && <PagedToolsSection   agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "mcps"       && <McpsSection         agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "memory"     && <MemorySection       agentId={agentId} />}
        {activeSection === "env"        && <EnvironmentSection  agent={agent} onSave={(d) => update.mutate(d)} />}
        {activeSection === "share"      && <ShareSection        agentId={agentId} />}
        {activeSection === "history"    && <HistorySection      agentId={agentId} />}
        {activeSection === "sessions"   && <SessionsSection     agentId={agentId} agentName={agent.name} />}
        {activeSection === "analytics"  && <AnalyticsSection    agentId={agentId} />}
        {activeSection === "files"      && <FilesSection        agent={agent} />}
      </div>
    </div>
  );
}
