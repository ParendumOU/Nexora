"use client";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FolderKanban, LayoutDashboard, RefreshCw, Bot } from "lucide-react";
import { projectsApi, agentsApi } from "@/lib/api";
import { KanbanBoard } from "@/components/kanban/board";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

type Project = { id: string; name: string; description: string | null };
type Agent = { id: string; name: string; agent_type: string };

export default function ProjectBoardPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [selectedAgent, setSelectedAgent] = useState<string>("");

  const { data: project } = useQuery<Project>({
    queryKey: ["project", params.id],
    queryFn: () => projectsApi.get(params.id).then((r) => r.data),
  });

  const { data: agents } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center gap-3 shrink-0">
        <button
          onClick={() => router.push(`/projects/${params.id}`)}
          className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <FolderKanban className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{project?.name}</span>
            <span className="text-xs text-muted-foreground">/</span>
            <span className="text-sm font-semibold flex items-center gap-1.5">
              <LayoutDashboard className="w-3.5 h-3.5" />
              Board
            </span>
          </div>
        </div>

        {/* Agent filter */}
        {agents && agents.length > 0 && (
          <div className="flex items-center gap-1.5">
            <Bot className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <select
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              className="text-xs bg-background border border-border rounded px-2 py-1 text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 max-w-[140px]"
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <button
          onClick={() => qc.invalidateQueries({ queryKey: ["board", params.id, selectedAgent || undefined] })}
          className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          title="Refresh board"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Board */}
      <div className="flex-1 overflow-hidden p-4">
        <KanbanBoard projectId={params.id} agentId={selectedAgent || undefined} />
      </div>
    </div>
  );
}
