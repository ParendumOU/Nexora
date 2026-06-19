"use client";
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Bot, Plus, Loader2, Search, X } from "lucide-react";
import { agentsApi, tasksApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { ActiveAgentsStrip, type ActiveTask } from "@/components/agents/ActiveAgentsStrip";
import { CreateAgentDialog } from "@/components/agents/CreateAgentDialog";
import { AgentRow, agentTypeLabel, type Agent } from "@/components/agents/AgentRow";
import { AgentTemplatePickerModal } from "@/components/agents/AgentTemplatePickerModal";
import type { AgentTemplate } from "@/data/agentTemplates";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AgentsPage() {
  // Template picker is shown first; create dialog opens after selection.
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const qc = useQueryClient();
  const router = useRouter();

  const { data: agents = [], isLoading } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });

  const { data: allTasks = [] } = useQuery<ActiveTask[]>({
    queryKey: ["tasks-global"],
    queryFn: () => tasksApi.listAll().then((r) => r.data as ActiveTask[]),
    refetchInterval: 3000,
  });

  const activeTasks = useMemo(
    () => allTasks.filter((t) => t.status === "in_progress" && t.assigned_agent_id),
    [allTasks]
  );

  const activeCountByAgent = useMemo(() => {
    const map: Record<string, number> = {};
    for (const t of activeTasks) {
      if (t.assigned_agent_id) map[t.assigned_agent_id] = (map[t.assigned_agent_id] ?? 0) + 1;
    }
    return map;
  }, [activeTasks]);

  const deleteAgent = useMutation({
    mutationFn: (id: string) => agentsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); toast.success("Agent deleted"); },
  });

  const agentTypes = useMemo(() => Array.from(new Set(agents.map((a) => a.agent_type))).sort(), [agents]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return agents.filter((a) => {
      const matchesSearch = !q || a.name.toLowerCase().includes(q) || (a.description ?? "").toLowerCase().includes(q) || a.agent_type.includes(q);
      const matchesType = filterType === "all" || a.agent_type === filterType;
      return matchesSearch && matchesType;
    });
  }, [agents, search, filterType]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold">Agents</h1>
          <p className="text-sm text-muted-foreground">{agents.length} agent{agents.length !== 1 ? "s" : ""} configured</p>
        </div>
        <Button onClick={() => setShowTemplatePicker(true)} size="sm" className="gap-1.5">
          <Plus className="w-3.5 h-3.5" />New Agent
        </Button>
      </div>

      {/* Active Now strip */}
      <ActiveAgentsStrip
        activeTasks={activeTasks}
        onNavigate={(chatId) => router.push(`/chat/${chatId}`)}
      />

      {/* Filter pills */}
      {!isLoading && agentTypes.length > 0 && (
        <div className="px-6 py-2 border-b border-border flex items-center gap-2 flex-wrap shrink-0">
          <button
            onClick={() => setFilterType("all")}
            className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors", filterType === "all" ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}
          >
            All ({agents.length})
          </button>
          {agentTypes.map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(filterType === type ? "all" : type)}
              className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors capitalize", filterType === type ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}
            >
              {agentTypeLabel(type)} ({agents.filter((a) => a.agent_type === type).length})
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="px-6 py-2.5 border-b border-border shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agents by name, type, or description…" className="pl-8 h-8 text-sm" />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60 gap-3 text-muted-foreground">
            <Bot className="w-10 h-10 opacity-20" />
            <p className="text-sm">{search || filterType !== "all" ? "No agents match your filters" : "No agents yet"}</p>
            {!search && filterType === "all" && (
              <Button size="sm" variant="outline" onClick={() => setShowTemplatePicker(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Create your first agent
              </Button>
            )}
          </div>
        ) : (
          <div>
            <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
              <Bot className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                {filtered.length} agent{filtered.length !== 1 ? "s" : ""}
                {(search || filterType !== "all") && ` of ${agents.length}`}
              </span>
            </div>
            {filtered.map((a) => (
              <AgentRow
                key={a.id}
                agent={a}
                isActive={!!activeCountByAgent[a.id]}
                activeCount={activeCountByAgent[a.id] ?? 0}
                onClick={() => router.push(`/agents/${a.id}`)}
                onDelete={() => deleteAgent.mutate(a.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Template picker — shown first when user clicks "New Agent" */}
      <AgentTemplatePickerModal
        open={showTemplatePicker}
        onClose={() => setShowTemplatePicker(false)}
        onSelect={({ template }) => {
          setSelectedTemplate(template);
          setShowTemplatePicker(false);
          setShowCreate(true);
        }}
      />

      {/* Create dialog — opened after template picker with optional pre-filled data */}
      <CreateAgentDialog
        open={showCreate}
        onClose={() => {
          setShowCreate(false);
          setSelectedTemplate(null);
        }}
        initialTemplate={selectedTemplate}
      />
    </div>
  );
}
