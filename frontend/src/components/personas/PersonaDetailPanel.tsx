"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { personasApi, skillsApi, mcpServersApi, toolsApi } from "@/lib/api";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { X, Save, Loader2, Zap, Network, Wrench, FileText, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { CapabilityTable, CapabilityRow } from "@/components/shared/CapabilityTable";
import {
  McpCapabilitySelector,
  type McpCapabilitySelection,
  type McpCapabilityServer,
} from "@/components/shared/McpCapabilitySelector";
import toast from "react-hot-toast";

export interface Persona {
  id: string;
  key: string;
  name: string;
  description: string | null;
  icon: string | null;
  soul: { personality?: string; communication_style?: string; expertise?: string[] };
  system_prompt: string | null;
  default_skills: string[];
  default_tools: string[];
  default_mcps: PersonaMcpConfig[];
  is_builtin?: boolean;
}

type PersonaMcpConfig = McpCapabilitySelection;
type CatalogMcp = McpCapabilityServer;

const COMMON_ICONS = ["💻","🧪","🔬","🎨","⚙️","📋","✨","🤖","🧠","🔧","🚀","🎯","📊","🔐","🌐"];

export function PersonaDetailPanel({ persona: initial, onClose }: { persona: Persona; onClose: () => void }) {
  const qc = useQueryClient();
  const isBuiltin = !!initial.is_builtin;
  const [capTab, setCapTab] = useState<"skills" | "mcps" | "tools" | "prompt" | "files">("skills");

  const [form, setForm] = useState({
    name: initial.name,
    description: initial.description ?? "",
    icon: initial.icon ?? "",
    soul: {
      personality: initial.soul?.personality ?? "",
      communication_style: initial.soul?.communication_style ?? "",
    },
    system_prompt: initial.system_prompt ?? "",
    default_skills: initial.default_skills ?? [],
    default_tools: initial.default_tools ?? [],
    default_mcps: initial.default_mcps ?? [],
  });

  useEffect(() => {
    setForm({
      name: initial.name,
      description: initial.description ?? "",
      icon: initial.icon ?? "",
      soul: {
        personality: initial.soul?.personality ?? "",
        communication_style: initial.soul?.communication_style ?? "",
      },
      system_prompt: initial.system_prompt ?? "",
      default_skills: initial.default_skills ?? [],
      default_tools: initial.default_tools ?? [],
      default_mcps: initial.default_mcps ?? [],
    });
  }, [initial.id]);

  const { data: builtinSkills = [] } = useQuery({
    queryKey: ["skills-builtin"],
    queryFn: () => skillsApi.builtin().then((r) => r.data as Array<{ key: string; name: string; description: string | null }>),
  });
  const { data: customSkills = [] } = useQuery({
    queryKey: ["skills"],
    queryFn: () => skillsApi.list().then((r) => r.data as Array<{ key: string; name: string; description: string | null }>),
  });
  const { data: catalogMcps = [] } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: () => mcpServersApi.list().then((r) => r.data as CatalogMcp[]),
  });
  const { data: builtinTools = [] } = useQuery({
    queryKey: ["tools-builtin"],
    queryFn: () => toolsApi.builtin().then((r) => r.data as Array<{ key: string; name: string; description: string | null }>),
  });
  const { data: customTools = [] } = useQuery({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list().then((r) => r.data as Array<{ key: string; name: string; description: string | null }>),
  });

  const save = useMutation({
    mutationFn: () => personasApi.update(initial.id, {
      name: form.name,
      description: form.description || undefined,
      icon: form.icon || undefined,
      soul: form.soul,
      system_prompt: form.system_prompt || undefined,
      default_skills: form.default_skills,
      default_tools: form.default_tools,
      default_mcps: form.default_mcps,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      toast.success("Persona saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  const allSkills = [...builtinSkills, ...customSkills];
  const allTools = [...builtinTools, ...customTools];

  const skillRows: CapabilityRow[] = allSkills.map((s) => ({
    key: s.key,
    label: s.name,
    description: s.description,
    isOn: form.default_skills.includes(s.key),
    onToggle: () => setForm((f) => ({
      ...f,
      default_skills: f.default_skills.includes(s.key)
        ? f.default_skills.filter((x) => x !== s.key)
        : [...f.default_skills, s.key],
    })),
  }));

  const toolRows: CapabilityRow[] = allTools.map((t) => ({
    key: t.key,
    label: t.name,
    description: t.description,
    isOn: form.default_tools.includes(t.key),
    onToggle: () => setForm((f) => ({
      ...f,
      default_tools: f.default_tools.includes(t.key)
        ? f.default_tools.filter((x) => x !== t.key)
        : [...f.default_tools, t.key],
    })),
  }));

  const counts = {
    skills: form.default_skills.length,
    mcps: form.default_mcps.length,
    tools: form.default_tools.length,
  };

  const toggleDefaultMcp = (mcp: CatalogMcp) =>
    setForm((f) => {
      const exists = f.default_mcps.some((entry) =>
        entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url
      );

      return {
        ...f,
        default_mcps: exists
          ? f.default_mcps.filter((entry) => !(entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url))
          : [...f.default_mcps, { server_id: mcp.id, name: mcp.name, url: mcp.url }],
      };
    });

  const setMcpAllowedTools = (mcp: CatalogMcp, allowedTools: string[]) =>
    setForm((f) => ({
      ...f,
      default_mcps: f.default_mcps.map((entry) => {
        if (!(entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url)) return entry;
        const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
        if (knownToolNames.length === 0 || allowedTools.length === knownToolNames.length) {
          const { allowed_tools: _ignored, ...rest } = entry;
          return rest;
        }
        return { ...entry, server_id: mcp.id, allowed_tools: allowedTools };
      }),
    }));

  const INPUT_CLS = "h-8 text-sm bg-background";
  const LABEL_CLS = "text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1";

  const { data: builtinFiles } = useQuery<{ files: Record<string, string> }>({
    queryKey: ["persona-builtin-files", initial.key],
    queryFn: () => personasApi.builtinFiles(initial.key).then((r) => r.data),
    enabled: isBuiltin,
  });

  const TABS = [
    { id: "skills" as const, label: "Skills", Icon: Zap, count: counts.skills },
    { id: "mcps" as const, label: "MCP Servers", Icon: Network, count: counts.mcps },
    { id: "tools" as const, label: "Tools", Icon: Wrench, count: counts.tools },
    { id: "prompt" as const, label: "Prompt", Icon: FileText, count: 0 },
    ...(isBuiltin ? [{ id: "files" as const, label: "Files", Icon: FileText, count: 0 }] : []),
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex flex-col bg-background border-l border-border w-full max-w-4xl h-full shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-accent flex items-center justify-center text-xl shrink-0">
              {initial.icon || "✨"}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold">{initial.name}</h2>
                <code className="text-[11px] text-muted-foreground font-mono">{initial.key}</code>
                {isBuiltin && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>}
              </div>
              {initial.description && <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">{initial.description}</p>}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="sm" variant="ghost"
              className="h-7 gap-1.5 text-xs"
              onClick={async () => {
                try {
                  const res = isBuiltin
                    ? await personasApi.builtinExport(initial.key)
                    : await personasApi.export(initial.id);
                  downloadBlob(res.data as Blob, `persona_${initial.key}.zip`);
                } catch { toast.error("Export failed"); }
              }}
            >
              <Download className="w-3.5 h-3.5" />Export
            </Button>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-accent text-muted-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left: identity form */}
          <div className="w-56 border-r border-border flex flex-col shrink-0 overflow-y-auto">
            <div className="p-4 space-y-4">
              {!isBuiltin && (
                <>
                  <div>
                    <p className={LABEL_CLS}>Name</p>
                    <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={INPUT_CLS} />
                  </div>
                  <div>
                    <p className={LABEL_CLS}>Description</p>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                      rows={3}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
                    />
                  </div>
                  <div>
                    <p className={LABEL_CLS}>Icon</p>
                    <Input value={form.icon} onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))} placeholder="emoji" className={cn(INPUT_CLS, "font-mono")} maxLength={4} />
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {COMMON_ICONS.map((emoji) => (
                        <button key={emoji} onClick={() => setForm((f) => ({ ...f, icon: emoji }))}
                          className={cn("w-7 h-7 rounded text-base flex items-center justify-center transition-colors", form.icon === emoji ? "bg-primary/20 ring-1 ring-primary" : "hover:bg-accent")}>
                          {emoji}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              <div>
                <p className={LABEL_CLS}>Personality</p>
                {isBuiltin ? (
                  <p className="text-xs text-foreground">{initial.soul?.personality || "—"}</p>
                ) : (
                  <Input value={form.soul.personality} onChange={(e) => setForm((f) => ({ ...f, soul: { ...f.soul, personality: e.target.value } }))} className={INPUT_CLS} placeholder="methodical, pragmatic…" />
                )}
              </div>
              <div>
                <p className={LABEL_CLS}>Communication style</p>
                {isBuiltin ? (
                  <p className="text-xs text-foreground">{initial.soul?.communication_style || "—"}</p>
                ) : (
                  <Input value={form.soul.communication_style} onChange={(e) => setForm((f) => ({ ...f, soul: { ...f.soul, communication_style: e.target.value } }))} className={INPUT_CLS} placeholder="concise, bullet-pointed…" />
                )}
              </div>
            </div>

            {!isBuiltin && (
              <div className="mt-auto p-4 border-t border-border">
                <Button size="sm" className="w-full gap-2" onClick={() => save.mutate()} disabled={save.isPending}>
                  {save.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  Save
                </Button>
              </div>
            )}
          </div>

          {/* Right: tabs */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Sub-tabs */}
            <div className="flex gap-1 p-3 border-b border-border shrink-0">
              <div className="flex gap-1 p-1 bg-accent/40 rounded-lg flex-1">
                {TABS.map(({ id, label, Icon, count }) => (
                  <button
                    key={id}
                    onClick={() => setCapTab(id)}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs font-medium transition-colors",
                      capTab === id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {label}
                    {count > 0 && (
                      <span className={cn("text-[10px] font-semibold", capTab === id ? "text-primary" : "text-muted-foreground")}>
                        {count}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {capTab === "skills" && (
                <CapabilityTable rows={skillRows} emptyText="No skills in catalog." readOnly={isBuiltin} />
              )}
              {false && capTab === "mcps" && (
                <div className="space-y-3">
                  {catalogMcps.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-8 px-4">No MCP servers configured.</p>
                  ) : (
                    <div className="border border-border rounded-lg overflow-hidden">
                      <div className="divide-y divide-border">
                        {catalogMcps.map((mcp) => {
                          const selected = form.default_mcps.find((entry) =>
                            entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url
                          );
                          const isOn = !!selected;
                          const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
                          const selectedToolNames = selected?.allowed_tools ?? knownToolNames;
                          const selectedToolCount = selectedToolNames.filter((tool) => knownToolNames.includes(tool)).length;

                          return (
                            <div key={mcp.id} className={cn("px-4 py-3", isOn ? "bg-primary/5" : "bg-card")}>
                              <button
                                onClick={() => !isBuiltin && toggleDefaultMcp(mcp)}
                                className={cn(
                                  "w-full flex items-center gap-3 text-left transition-colors",
                                  !isBuiltin && "cursor-pointer"
                                )}
                              >
                                <div className={cn(
                                  "w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors",
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
                                  <p className="text-[11px] text-muted-foreground">
                                    {mcp.description ?? mcp.url}
                                  </p>
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
                                            onClick={() => !isBuiltin && setMcpAllowedTools(mcp, nextTools)}
                                            className={cn(
                                              "transition-colors",
                                              !isBuiltin && "cursor-pointer",
                                              toolOn ? "bg-primary/5 hover:bg-primary/8" : !isBuiltin && "hover:bg-accent/30"
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
                                            <td className="px-3 py-2.5 text-muted-foreground">
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
                  )}
                  <p className="text-[11px] text-muted-foreground">
                    Select the MCP servers this persona can use. If a server has discovered tools, you can restrict it to only some of them.
                    {isBuiltin && " Built-in personas are read-only."}
                  </p>
                </div>
              )}
              {capTab === "mcps" && (
                <McpCapabilitySelector
                  catalogMcps={catalogMcps}
                  selectedMcps={form.default_mcps}
                  onToggleMcp={toggleDefaultMcp}
                  onSetAllowedTools={setMcpAllowedTools}
                  emptyText="No MCP servers configured."
                  readOnly={isBuiltin}
                  footerText={`Select the MCP servers this persona can use. If a server has discovered tools, you can restrict it to only some of them.${isBuiltin ? " Built-in personas are read-only." : ""}`}
                />
              )}
              {capTab === "tools" && (
                <CapabilityTable rows={toolRows} emptyText="No tools available." readOnly={isBuiltin} />
              )}
              {capTab === "prompt" && (
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground">The system prompt shapes how this persona behaves in every conversation.</p>
                  {isBuiltin ? (
                    <pre className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-sans bg-accent/20 rounded-lg p-4 border border-border">
                      {initial.system_prompt || "No system prompt defined."}
                    </pre>
                  ) : (
                    <textarea
                      value={form.system_prompt}
                      onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
                      rows={16}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
                      placeholder="You are a senior software developer…"
                    />
                  )}
                </div>
              )}

              {capTab === "files" && (
                <div className="space-y-3">
                  {Object.entries(builtinFiles?.files ?? {}).length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-8">No seed files for this persona.</p>
                  ) : (
                    Object.entries(builtinFiles?.files ?? {}).map(([name, content]) => (
                      <div key={name} className="border border-border rounded-lg overflow-hidden">
                        <div className="px-3 py-2 bg-accent/20 border-b border-border flex items-center gap-2">
                          <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-xs font-mono font-medium">{name}</span>
                        </div>
                        <pre className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono px-4 py-3 max-h-80 overflow-auto">
                          {content}
                        </pre>
                      </div>
                    ))
                  )}
                </div>
              )}
              {capTab !== "prompt" && capTab !== "files" && (
                <p className="text-[11px] text-muted-foreground mt-3">
                  {counts.skills} skill{counts.skills !== 1 ? "s" : ""} · {counts.mcps} MCP{counts.mcps !== 1 ? "s" : ""} · {counts.tools} tool{counts.tools !== 1 ? "s" : ""} selected as defaults
                  {isBuiltin && " (read-only — clone to customise)"}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
