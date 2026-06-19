"use client";
import { Bot, Trash2, ChevronRight, Network, Wrench, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface Agent {
  id: string;
  name: string;
  agent_type: string;
  description?: string;
  skills: string[];
  tools?: string[];
  env_vars?: Record<string, string>;
  mcps?: unknown[];
  max_subagents?: number;
  is_builtin?: boolean;
}

export function agentTypeLabel(type: string) {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function AgentRow({ agent, isActive, activeCount, onClick, onDelete }: {
  agent: Agent;
  isActive: boolean;
  activeCount: number;
  onClick: () => void;
  onDelete: () => void;
}) {
  const toolCount = agent.tools?.length ?? 0;
  const mcpCount = agent.mcps?.length ?? 0;
  const envCount = agent.env_vars ? Object.keys(agent.env_vars).length : 0;

  return (
    <div
      onClick={onClick}
      className="flex items-center gap-4 px-5 py-3.5 hover:bg-accent/30 transition-colors group cursor-pointer border-b border-border/60 last:border-0"
    >
      <div className={cn(
        "w-8 h-8 rounded-lg flex items-center justify-center shrink-0 relative",
        isActive ? "bg-cyan-950/40 border border-cyan-500/30" : "bg-accent"
      )}>
        <Bot className={cn("w-4 h-4", isActive ? "text-cyan-400" : "text-accent-foreground")} />
        {isActive && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-cyan-400 animate-pulse border-2 border-background" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-medium text-foreground">{agent.name}</span>
          {isActive && (
            <span className="text-[10px] text-cyan-400 bg-cyan-400/10 border border-cyan-400/20 rounded-full px-1.5 py-0 leading-4">
              {activeCount} running
            </span>
          )}
          <span className="text-[11px] text-muted-foreground capitalize">{agentTypeLabel(agent.agent_type)}</span>
          {agent.is_builtin && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">built-in</Badge>
          )}
        </div>
        {agent.description && (
          <p className="text-xs text-muted-foreground leading-snug line-clamp-1">{agent.description}</p>
        )}
        {agent.skills.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {agent.skills.slice(0, 4).map((s) => (
              <Badge key={s} variant="muted" className="text-[10px] px-1.5 py-0">{s}</Badge>
            ))}
            {agent.skills.length > 4 && (
              <Badge variant="muted" className="text-[10px] px-1.5 py-0">+{agent.skills.length - 4}</Badge>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 text-[11px] text-muted-foreground shrink-0">
        {mcpCount > 0 && (
          <span className="flex items-center gap-1"><Network className="w-3 h-3" />{mcpCount}</span>
        )}
        {toolCount > 0 && (
          <span className="flex items-center gap-1"><Wrench className="w-3 h-3" />{toolCount}</span>
        )}
        {envCount > 0 && (
          <span className="flex items-center gap-1"><Zap className="w-3 h-3" />{envCount} env</span>
        )}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        {!agent.is_builtin && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-destructive transition-all text-muted-foreground"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
        <ChevronRight className="w-4 h-4 text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </div>
  );
}
