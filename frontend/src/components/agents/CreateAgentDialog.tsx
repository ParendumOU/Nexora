"use client";
import { useState, useEffect } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { agentsApi, skillsApi, mcpServersApi, toolsApi, personasApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  McpCapabilitySelector,
  type McpCapabilitySelection,
  type McpCapabilityServer,
} from "@/components/shared/McpCapabilitySelector";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import type { Persona } from "@/components/personas/PersonaDetailPanel";
import { Sparkles, Zap, Network, Wrench, ChevronRight, Loader2, X, LayoutTemplate } from "lucide-react";
import type { AgentTemplate } from "@/data/agentTemplates";

// ─── Template types ────────────────────────────────────────────────────────────

/** Backend/API agent template (from /agents/templates endpoint) */
interface BackendAgentTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  source: string;
  agent_type: string;
  model_pref: string;
  system_prompt_preview: string;
  system_prompt: string;
  tools: string[];
  skills: string[];
  soul: Record<string, unknown>;
  temperature: number;
}

const TEMPLATE_CATEGORIES = ["All", "Productivity", "Code", "Customer Support", "Research", "DevOps"] as const;
type TemplateCategory = typeof TEMPLATE_CATEGORIES[number];

const CATEGORY_EMOJIS: Record<string, string> = {
  Productivity: "📋",
  Code: "💻",
  "Customer Support": "🎧",
  Research: "🔬",
  DevOps: "⚙️",
};

function agentTypeEmoji(agentType: string): string {
  const map: Record<string, string> = {
    project_manager: "📋",
    coordinator: "🤝",
    devops: "⚙️",
    architect: "🏗️",
    developer: "💻",
    qa_engineer: "🧪",
    researcher: "🔬",
    support: "🎧",
    custom: "✨",
  };
  return map[agentType] ?? "🤖";
}

type AgentMcpConfig = McpCapabilitySelection;
type CatalogMcp = McpCapabilityServer;

// ─── Inline capability table ───────────────────────────────────────────────────

function CapabilityTable<T extends { label: string; description: string | null; isOn: boolean; onToggle: () => void }>({
  rows,
  emptyText,
}: {
  rows: T[];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-8">{emptyText}</p>;
  }
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="overflow-y-auto max-h-64">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-accent/40 border-b border-border">
              <th className="w-9 px-3 py-2" />
              <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Name</th>
              <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.map((row, i) => (
              <tr
                key={i}
                onClick={row.onToggle}
                className={cn(
                  "cursor-pointer transition-colors",
                  row.isOn ? "bg-primary/5 hover:bg-primary/8" : "hover:bg-accent/30"
                )}
              >
                <td className="px-3 py-2.5">
                  <div className={cn(
                    "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                    row.isOn ? "bg-primary border-primary" : "border-border bg-background"
                  )}>
                    {row.isOn && <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>}
                  </div>
                </td>
                <td className="px-3 py-2.5 font-medium text-foreground whitespace-nowrap">{row.label}</td>
                <td className="px-3 py-2.5 text-muted-foreground max-w-xs">
                  <span className="line-clamp-2 leading-snug">{row.description ?? "—"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Create dialog ────────────────────────────────────────────────────────────

const STEPS = ["Template", "Persona", "Identity", "Capabilities", "Environment"] as const;

export function CreateAgentDialog({
  open,
  onClose,
  initialTemplate,
}: {
  open: boolean;
  onClose: () => void;
  /** When set, the dialog opens at the Identity step with fields pre-filled from this template. */
  initialTemplate?: AgentTemplate | null;
}) {
  const qc = useQueryClient();

  // If an initial template is provided, start at Identity (step 2) so the
  // user goes straight into editing the pre-filled fields.
  const [step, setStep] = useState(initialTemplate ? 2 : 0);
  const [capTab, setCapTab] = useState<"skills" | "mcps" | "tools">("skills");
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    initialTemplate ? `local:${initialTemplate.id}` : null
  );
  const [templateCategory, setTemplateCategory] = useState<TemplateCategory>("All");

  // Derive initial form values from the template (if any)
  const [form, setForm] = useState(() => {
    if (initialTemplate) {
      return {
        name: initialTemplate.name,
        agent_type: initialTemplate.agentType,
        description: initialTemplate.description,
        soul: {
          personality: initialTemplate.persona,
          expertise: [] as string[],
          communication_style: "",
        },
        system_prompt: initialTemplate.systemPrompt,
        skills: initialTemplate.suggestedSkills,
        tools: initialTemplate.suggestedTools,
        model_pref: "",
        env_vars: {} as Record<string, string>,
        mcps: [] as AgentMcpConfig[],
        max_subagents: 5,
        max_concurrency: 2,
      };
    }
    return {
      name: "", agent_type: "custom", description: "",
      soul: { personality: "", expertise: [] as string[], communication_style: "" },
      system_prompt: "", skills: [] as string[], tools: [] as string[], model_pref: "",
      env_vars: {} as Record<string, string>,
      mcps: [] as AgentMcpConfig[],
      max_subagents: 5, max_concurrency: 2,
    };
  });

  // Re-initialise when initialTemplate changes (e.g. user picks a different template and
  // the parent re-mounts / re-opens the dialog)
  useEffect(() => {
    if (initialTemplate) {
      setStep(2);
      setSelectedTemplateId(`local:${initialTemplate.id}`);
      setForm({
        name: initialTemplate.name,
        agent_type: initialTemplate.agentType,
        description: initialTemplate.description,
        soul: {
          personality: initialTemplate.persona,
          expertise: [],
          communication_style: "",
        },
        system_prompt: initialTemplate.systemPrompt,
        skills: initialTemplate.suggestedSkills,
        tools: initialTemplate.suggestedTools,
        model_pref: "",
        env_vars: {},
        mcps: [],
        max_subagents: 5,
        max_concurrency: 2,
      });
    } else if (!initialTemplate && open) {
      // Opened without a template — reset to step 0
      setStep(0);
      setSelectedTemplateId(null);
      setForm({
        name: "", agent_type: "custom", description: "",
        soul: { personality: "", expertise: [], communication_style: "" },
        system_prompt: "", skills: [], tools: [], model_pref: "",
        env_vars: {}, mcps: [], max_subagents: 5, max_concurrency: 2,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTemplate, open]);
  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvVal, setNewEnvVal] = useState("");
  const [loading, setLoading] = useState(false);

  const { data: templates = [] } = useQuery<BackendAgentTemplate[]>({
    queryKey: ["agent-templates"],
    queryFn: () => agentsApi.getTemplates().then((r) => r.data),
  });

  const { data: builtinPersonas = [] } = useQuery<Persona[]>({
    queryKey: ["personas-builtin"],
    queryFn: () => personasApi.builtin().then((r) => r.data),
  });
  const { data: customPersonas = [] } = useQuery<Persona[]>({
    queryKey: ["personas"],
    queryFn: () => personasApi.list().then((r) => r.data),
  });
  const { data: builtinSkills = [] } = useQuery({
    queryKey: ["skills-builtin"],
    queryFn: () => skillsApi.builtin().then((r) => r.data),
  });
  const { data: customSkills = [] } = useQuery({
    queryKey: ["skills"],
    queryFn: () => skillsApi.list().then((r) => r.data),
  });
  const { data: catalogMcps = [] } = useQuery<CatalogMcp[]>({
    queryKey: ["mcp-servers"],
    queryFn: () => mcpServersApi.list().then((r) => r.data as CatalogMcp[]),
  });
  const { data: builtinTools = [] } = useQuery<Array<{ key: string; name: string; description: string | null; category: string }>>({
    queryKey: ["tools-builtin"],
    queryFn: () => toolsApi.builtin().then((r) => r.data),
  });
  const { data: customTools = [] } = useQuery<Array<{ key: string; name: string; description: string | null; category: string }>>({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list().then((r) => r.data),
  });

  const allPersonas = [...builtinPersonas, ...customPersonas];
  const allSkills = [
    ...(builtinSkills as Array<{ key: string; name: string; description: string | null }>),
    ...(customSkills as Array<{ key: string; name: string; description: string | null }>),
  ];
  const allTools = [...builtinTools, ...customTools];

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const selectTemplate = (tpl: BackendAgentTemplate) => {
    setSelectedTemplateId(tpl.id);
    setForm((f) => ({
      ...f,
      name: tpl.name,
      agent_type: tpl.agent_type || "custom",
      description: tpl.description || "",
      system_prompt: tpl.system_prompt || "",
      model_pref: tpl.model_pref || "",
      tools: tpl.tools || [],
      skills: tpl.skills || [],
      soul: {
        personality: (tpl.soul?.personality as string) || f.soul.personality,
        expertise: (tpl.soul?.expertise as string[]) || f.soul.expertise,
        communication_style: (tpl.soul?.communication_style as string) || f.soul.communication_style,
      },
    }));
  };

  const selectPersona = (persona: Persona) => {
    setSelectedPersonaId(persona.id);
    setForm((f) => ({
      ...f,
      agent_type: persona.key,
      soul: {
        personality: persona.soul?.personality ?? f.soul.personality,
        expertise: f.soul.expertise,
        communication_style: persona.soul?.communication_style ?? f.soul.communication_style,
      },
      system_prompt: persona.system_prompt ?? f.system_prompt,
      skills: persona.default_skills ?? [],
      tools: persona.default_tools ?? [],
      mcps: persona.default_mcps ?? [],
    }));
  };

  const toggleSkill = (key: string) =>
    setForm((f) => ({ ...f, skills: f.skills.includes(key) ? f.skills.filter((x) => x !== key) : [...f.skills, key] }));

  const toggleTool = (key: string) =>
    setForm((f) => ({ ...f, tools: f.tools.includes(key) ? f.tools.filter((x) => x !== key) : [...f.tools, key] }));

  const toggleMcp = (mcp: CatalogMcp) =>
    setForm((f) => ({
      ...f,
      mcps: f.mcps.some((entry) => entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url)
        ? f.mcps.filter((entry) => !(entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url))
        : [...f.mcps, { server_id: mcp.id, name: mcp.name, url: mcp.url }],
    }));

  const setMcpAllowedTools = (mcp: CatalogMcp, allowedTools: string[]) =>
    setForm((f) => ({
      ...f,
      mcps: f.mcps.map((entry) => {
        if (!(entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url)) return entry;
        const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
        if (knownToolNames.length === 0 || allowedTools.length === knownToolNames.length) {
          const { allowed_tools: _ignored, ...rest } = entry;
          return rest;
        }
        return { ...entry, server_id: mcp.id, allowed_tools: allowedTools };
      }),
    }));

  const addEnvVar = () => {
    if (!newEnvKey.trim()) return;
    setForm((f) => ({ ...f, env_vars: { ...f.env_vars, [newEnvKey.trim()]: newEnvVal } }));
    setNewEnvKey(""); setNewEnvVal("");
  };

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error("Agent name is required"); return; }
    setLoading(true);
    try {
      await agentsApi.create(form);
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent created");
      onClose();
      setStep(0); setCapTab("skills"); setSelectedPersonaId(null); setSelectedTemplateId(null); setTemplateCategory("All");
      setForm({ name: "", agent_type: "custom", description: "", soul: { personality: "", expertise: [], communication_style: "" }, system_prompt: "", skills: [], tools: [], model_pref: "", env_vars: {}, mcps: [], max_subagents: 5, max_concurrency: 2 });
    } catch {
      toast.error("Failed to create agent");
    } finally {
      setLoading(false);
    }
  };

  const skillRows = allSkills.map((s) => ({
    label: s.name,
    description: s.description,
    isOn: form.skills.includes(s.key),
    onToggle: () => toggleSkill(s.key),
  }));

  const toolRows = allTools.map((t) => ({
    label: t.name,
    description: t.description,
    isOn: form.tools.includes(t.key),
    onToggle: () => toggleTool(t.key),
  }));

  const capCounts = {
    skills: form.skills.length,
    mcps: form.mcps.length,
    tools: form.tools.length,
  };

  const selectedPersona = allPersonas.find((p) => p.id === selectedPersonaId);

  useEffect(() => {
    setForm((f) => ({
      ...f,
      mcps: f.mcps.map((entry) => {
        const match = catalogMcps.find((mcp) => entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url);
        if (!match) return entry;
        return { ...entry, server_id: match.id, name: match.name, url: match.url };
      }),
    }));
  }, [catalogMcps]);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-2xl bg-card border border-border rounded-2xl shadow-2xl overflow-hidden">

          {/* Step tabs */}
          <div className="flex border-b border-border">
            {STEPS.map((s, i) => (
              <button
                key={s}
                onClick={() => setStep(i)}
                className={cn(
                  "flex-1 py-3 text-xs font-medium transition-colors",
                  step === i ? "text-primary border-b-2 border-primary" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {i + 1}. {s}
              </button>
            ))}
          </div>

          <div className="p-6">
            {/* ── Step 0: Template ── */}
            {step === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">Start from a template or build from scratch.</p>

                {/* Category filter */}
                <div className="flex flex-wrap gap-1.5">
                  {TEMPLATE_CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      onClick={() => setTemplateCategory(cat)}
                      className={cn(
                        "text-xs px-2.5 py-1 rounded-full border transition-colors",
                        templateCategory === cat
                          ? "bg-primary text-primary-foreground border-primary"
                          : "border-border hover:bg-accent"
                      )}
                    >
                      {cat !== "All" && CATEGORY_EMOJIS[cat] ? `${CATEGORY_EMOJIS[cat]} ` : ""}{cat}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-2 max-h-72 overflow-y-auto pr-1">
                  {/* Start from scratch card */}
                  {(templateCategory === "All") && (
                    <button
                      onClick={() => { setSelectedTemplateId(null); setStep(1); }}
                      className={cn(
                        "flex items-start gap-3 p-3 rounded-xl border text-left transition-colors col-span-1",
                        !selectedTemplateId
                          ? "border-primary bg-primary/5"
                          : "border-dashed border-border hover:border-primary/40 hover:bg-accent/50"
                      )}
                    >
                      <span className="text-xl shrink-0 mt-0.5">✨</span>
                      <div className="min-w-0">
                        <div className="text-xs font-semibold">Start from scratch</div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">Blank agent — configure everything yourself</div>
                      </div>
                    </button>
                  )}

                  {/* Template cards */}
                  {templates
                    .filter((t) => templateCategory === "All" || t.category === templateCategory)
                    .map((tpl) => (
                      <button
                        key={tpl.id}
                        onClick={() => selectTemplate(tpl)}
                        className={cn(
                          "flex items-start gap-3 p-3 rounded-xl border text-left transition-colors",
                          selectedTemplateId === tpl.id
                            ? "border-primary bg-primary/5"
                            : "border-border hover:border-primary/40 hover:bg-accent/50"
                        )}
                      >
                        <span className="text-xl shrink-0 mt-0.5">{agentTypeEmoji(tpl.agent_type)}</span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-xs font-semibold">{tpl.name}</span>
                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-accent text-muted-foreground border border-border/60 whitespace-nowrap">
                              {tpl.category}
                            </span>
                          </div>
                          {tpl.description && (
                            <div className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">{tpl.description}</div>
                          )}
                          {(tpl.skills.length + tpl.tools.length) > 0 && (
                            <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground">
                              {tpl.skills.length > 0 && <span>{tpl.skills.length} skill{tpl.skills.length !== 1 ? "s" : ""}</span>}
                              {tpl.tools.length > 0 && <span>{tpl.tools.length} tool{tpl.tools.length !== 1 ? "s" : ""}</span>}
                            </div>
                          )}
                        </div>
                      </button>
                    ))}

                  {templates.filter((t) => templateCategory === "All" || t.category === templateCategory).length === 0 && (
                    <div className="col-span-2 text-center py-8 text-xs text-muted-foreground">
                      No templates in this category.
                    </div>
                  )}
                </div>

                {selectedTemplateId && (
                  <div className="flex items-center gap-2 text-xs text-primary bg-primary/5 border border-primary/20 rounded-lg px-3 py-2">
                    <LayoutTemplate className="w-3.5 h-3.5 shrink-0" />
                    <span>
                      <strong>{templates.find((t) => t.id === selectedTemplateId)?.name}</strong> selected — fields pre-filled on next steps
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* ── Step 1: Persona ── */}
            {step === 1 && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">Choose a persona to pre-configure capabilities and personality.</p>
                <div className="grid grid-cols-2 gap-2 max-h-80 overflow-y-auto pr-1">
                  {allPersonas.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => selectPersona(p)}
                      className={cn(
                        "flex items-start gap-3 p-3 rounded-xl border text-left transition-colors",
                        selectedPersonaId === p.id
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-primary/40 hover:bg-accent/50"
                      )}
                    >
                      <span className="text-xl shrink-0 mt-0.5">{p.icon || "✨"}</span>
                      <div className="min-w-0">
                        <div className="text-xs font-semibold">{p.name}</div>
                        {p.description && (
                          <div className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">{p.description}</div>
                        )}
                        {(p.default_skills.length + p.default_tools.length + p.default_mcps.length) > 0 && (
                          <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground">
                            {p.default_skills.length > 0 && <span>{p.default_skills.length} skills</span>}
                            {p.default_tools.length > 0 && <span>{p.default_tools.length} tools</span>}
                            {p.default_mcps.length > 0 && <span>{p.default_mcps.length} MCPs</span>}
                          </div>
                        )}
                      </div>
                    </button>
                  ))}
                  {allPersonas.length === 0 && (
                    <div className="col-span-2 text-center py-8 text-xs text-muted-foreground">
                      No personas available. You can still create an agent without one.
                    </div>
                  )}
                </div>
                {selectedPersona && (
                  <div className="flex items-center gap-2 text-xs text-primary bg-primary/5 border border-primary/20 rounded-lg px-3 py-2">
                    <span>{selectedPersona.icon}</span>
                    <span>
                      <strong>{selectedPersona.name}</strong> selected — capabilities will be pre-filled on step 4
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* ── Step 2: Identity ── */}
            {step === 2 && (
              <div className="space-y-3">
                {(selectedTemplateId || selectedPersona) && (
                  <div className="flex items-center gap-2 text-xs text-primary bg-primary/5 border border-primary/20 rounded-lg px-3 py-2">
                    <Sparkles className="w-3.5 h-3.5 shrink-0" />
                    Pre-filled with <strong>{selectedTemplateId ? templates.find((t) => t.id === selectedTemplateId)?.name : selectedPersona?.name}</strong> defaults — edit as needed
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Name *</label>
                  <Input placeholder="Alex" value={form.name} onChange={set("name")} autoFocus />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Personality</label>
                  <Input placeholder="methodical, detail-oriented, prefers TypeScript" value={form.soul.personality}
                    onChange={(e) => setForm((f) => ({ ...f, soul: { ...f.soul, personality: e.target.value } }))} />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">System prompt</label>
                  <textarea placeholder="You are a senior developer specializing in…" value={form.system_prompt}
                    onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
                    className="flex h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none" />
                </div>
              </div>
            )}

            {/* ── Step 3: Capabilities ── */}
            {step === 3 && (
              <div className="space-y-4">
                {/* Sub-tabs */}
                <div className="flex gap-1 p-1 bg-accent/40 rounded-lg">
                  {(["skills", "mcps", "tools"] as const).map((tab) => {
                    const icons = { skills: Zap, mcps: Network, tools: Wrench };
                    const labels = { skills: "Skills", mcps: "MCP Servers", tools: "Tools" };
                    const Icon = icons[tab];
                    return (
                      <button
                        key={tab}
                        onClick={() => setCapTab(tab)}
                        className={cn(
                          "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs font-medium transition-colors",
                          capTab === tab ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                        )}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        {labels[tab]}
                        {capCounts[tab] > 0 && (
                          <span className={cn("text-[10px] font-semibold", capTab === tab ? "text-primary" : "text-muted-foreground")}>
                            {capCounts[tab]}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {capTab === "skills" && <CapabilityTable rows={skillRows} emptyText="No skills in catalog yet." />}
                {false && capTab === "mcps" && (
                  catalogMcps.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-8">No MCP servers configured. Add some in the MCP Servers section.</p>
                  ) : (
                    <div className="border border-border rounded-lg overflow-hidden">
                      <div className="divide-y divide-border">
                        {catalogMcps.map((mcp) => {
                          const selected = form.mcps.find((entry) =>
                            entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url
                          );
                          const isOn = !!selected;
                          const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
                          const selectedToolNames = selected?.allowed_tools ?? knownToolNames;
                          const selectedToolCount = selectedToolNames.filter((tool) => knownToolNames.includes(tool)).length;

                          return (
                            <div key={mcp.id} className={cn("px-4 py-3", isOn ? "bg-primary/5" : "bg-card")}>
                              <button
                                onClick={() => toggleMcp(mcp)}
                                className="w-full flex items-center gap-3 text-left cursor-pointer transition-colors"
                              >
                                <div className={cn(
                                  "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                                  isOn ? "bg-primary border-primary" : "border-border bg-background"
                                )}>
                                  {isOn && <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-foreground">{mcp.name}</span>
                                    {knownToolNames.length > 0 && (
                                      <span className="text-[10px] text-muted-foreground">
                                        {isOn
                                          ? (selectedToolCount === knownToolNames.length
                                            ? `All ${knownToolNames.length} tools`
                                            : `${selectedToolCount}/${knownToolNames.length} tools`)
                                          : `${knownToolNames.length} tools discovered`}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-[11px] text-muted-foreground">{mcp.description ?? mcp.url}</p>
                                </div>
                              </button>
                              {isOn && knownToolNames.length > 0 && (
                                <div className="mt-3 ml-7 border border-border rounded-lg overflow-hidden">
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="bg-accent/20 border-b border-border">
                                        <th className="w-9 px-3 py-2" />
                                        <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Tool</th>
                                        <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-border/60">
                                      {mcp.known_tools.map((tool) => {
                                        const toolOn = selectedToolNames.includes(tool.name);
                                        const nextTools = toolOn
                                          ? selectedToolNames.filter((name) => name !== tool.name)
                                          : [...selectedToolNames, tool.name];

                                        return (
                                          <tr
                                            key={tool.name}
                                            onClick={() => setMcpAllowedTools(mcp, nextTools)}
                                            className={cn(
                                              "cursor-pointer transition-colors",
                                              toolOn ? "bg-primary/5 hover:bg-primary/8" : "hover:bg-accent/30"
                                            )}
                                          >
                                            <td className="px-3 py-2.5">
                                              <div className={cn(
                                                "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                                                toolOn ? "bg-primary border-primary" : "border-border bg-background"
                                              )}>
                                                {toolOn && <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>}
                                              </div>
                                            </td>
                                            <td className="px-3 py-2.5 font-mono text-foreground whitespace-nowrap">{tool.name}</td>
                                            <td className="px-3 py-2.5 text-muted-foreground max-w-xs">
                                              <span className="line-clamp-2 leading-snug">{tool.description || "—"}</span>
                                            </td>
                                          </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )
                )}
                {capTab === "mcps" && (
                  <McpCapabilitySelector
                    catalogMcps={catalogMcps}
                    selectedMcps={form.mcps}
                    onToggleMcp={toggleMcp}
                    onSetAllowedTools={setMcpAllowedTools}
                    emptyText="No MCP servers configured. Add some in the MCP Servers section."
                  />
                )}
                {capTab === "tools" && <CapabilityTable rows={toolRows} emptyText="No tools available." />}

                <p className="text-[11px] text-muted-foreground">
                  {capCounts.skills} skill{capCounts.skills !== 1 ? "s" : ""} · {capCounts.mcps} MCP{capCounts.mcps !== 1 ? "s" : ""} · {capCounts.tools} tool{capCounts.tools !== 1 ? "s" : ""} selected
                </p>
              </div>
            )}

            {/* ── Step 4: Environment ── */}
            {step === 4 && (
              <div className="space-y-5">
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Concurrency</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Max sub-agents</label>
                      <Input type="number" min={1} max={20} value={form.max_subagents}
                        onChange={(e) => setForm((f) => ({ ...f, max_subagents: parseInt(e.target.value) || 5 }))} />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Max concurrency</label>
                      <Input type="number" min={1} max={10} value={form.max_concurrency}
                        onChange={(e) => setForm((f) => ({ ...f, max_concurrency: parseInt(e.target.value) || 2 }))} />
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Environment Variables</p>
                  <p className="text-[11px] text-muted-foreground">Injected when the agent runs CLI tools (git, bash, etc.)</p>
                  <div className="space-y-1">
                    {Object.entries(form.env_vars).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2 bg-accent/30 rounded px-2 py-1">
                        <code className="text-xs font-mono text-foreground flex-1">{k}=<span className="text-muted-foreground">{v}</span></code>
                        <button
                          onClick={() => setForm((f) => { const e = { ...f.env_vars }; delete e[k]; return { ...f, env_vars: e }; })}
                          className="text-muted-foreground hover:text-destructive"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input placeholder="KEY" value={newEnvKey} onChange={(e) => setNewEnvKey(e.target.value)} className="font-mono text-xs" />
                    <Input placeholder="value" value={newEnvVal} onChange={(e) => setNewEnvVal(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && addEnvVar()} className="font-mono text-xs flex-1" />
                    <Button size="sm" variant="outline" onClick={addEnvVar}>Add</Button>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2 justify-between px-6 py-4 border-t border-border">
            <Button variant="ghost" onClick={onClose} disabled={loading}>Cancel</Button>
            <div className="flex gap-2">
              {step > 0 && <Button variant="outline" onClick={() => setStep(step - 1)}>Back</Button>}
              {step < 4 ? (
                <Button onClick={() => setStep(step + 1)}>
                  {step === 0 && !selectedTemplateId ? "Skip" : step === 1 && !selectedPersonaId ? "Skip" : "Next"}
                  <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              ) : (
                <Button onClick={handleCreate} disabled={loading}>
                  {loading ? <><Loader2 className="w-4 h-4 animate-spin mr-1.5" />Creating…</> : "Create Agent"}
                </Button>
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
