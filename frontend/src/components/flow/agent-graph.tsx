"use client";

import { useMemo } from "react";
import { TaskData } from "@/components/chat/task-panel";

// ── Layout constants ──────────────────────────────────────────────────────────
const NW = 184;
const NH = 64;
const HG = 52;
const VG = 88;
const PAD = 56;

// ── Types ─────────────────────────────────────────────────────────────────────
interface GNode {
  id: string;
  name: string;
  agentType?: string;
  x: number;
  y: number;
  total: number;
  running: number;
  completed: number;
  failed: number;
}
interface GEdge { from: string; to: string }

export interface KnownAgent {
  id: string;
  name: string;
  agent_type: string;
}

// Agent type → default hierarchy level when no task edges exist
const TYPE_LEVEL: Record<string, number> = {
  project_manager: 0,
  developer: 1, qa_engineer: 1, researcher: 1, designer: 1, devops: 1,
  custom: 1,
};

// ── Graph builder ─────────────────────────────────────────────────────────────
function buildGraph(
  tasks: TaskData[],
  allAgents?: KnownAgent[],
): {
  nodes: GNode[];
  edges: GEdge[];
  pos: Map<string, { cx: number; cy: number }>;
  w: number;
  h: number;
} {
  const empty = { nodes: [], edges: [], pos: new Map<string, { cx: number; cy: number }>(), w: 360, h: 260 };
  const hasAgents = allAgents && allAgents.length > 0;
  if (!tasks.length && !hasAgents) return empty;

  const byId = new Map(tasks.map((t) => [t.id, t]));
  const depthCache = new Map<string, number>();

  function taskDepth(id: string, visited = new Set<string>()): number {
    if (depthCache.has(id)) return depthCache.get(id)!;
    if (visited.has(id)) return 0;
    visited.add(id);
    const t = byId.get(id);
    const d = t?.parent_id ? 1 + taskDepth(t.parent_id, new Set(visited)) : 0;
    depthCache.set(id, d);
    return d;
  }

  type Stats = {
    name: string; agentType?: string; minDepth: number;
    total: number; running: number; completed: number; failed: number;
  };
  const agentMap = new Map<string, Stats>();

  // Seed from allAgents first so every known agent becomes a node
  if (allAgents) {
    for (const a of allAgents) {
      agentMap.set(a.id, {
        name: a.name, agentType: a.agent_type,
        minDepth: TYPE_LEVEL[a.agent_type] ?? 1,
        total: 0, running: 0, completed: 0, failed: 0,
      });
    }
  }

  // Accumulate task stats
  for (const t of tasks) {
    const aid = t.assigned_agent_id ?? "__none__";
    const d = taskDepth(t.id);
    const s = agentMap.get(aid);
    if (!s) {
      agentMap.set(aid, {
        name: t.assigned_agent_name ?? "Unassigned",
        minDepth: d, total: 1,
        running: t.status === "running" ? 1 : 0,
        completed: t.status === "completed" ? 1 : 0,
        failed: t.status === "failed" ? 1 : 0,
      });
    } else {
      s.minDepth = Math.min(s.minDepth, d);
      s.total++;
      if (t.status === "running") s.running++;
      if (t.status === "completed") s.completed++;
      if (t.status === "failed") s.failed++;
    }
  }

  // Build edges from task parent→child agent delegation
  const edgeSet = new Set<string>();
  const edges: GEdge[] = [];
  for (const t of tasks) {
    if (!t.parent_id) continue;
    const parent = byId.get(t.parent_id);
    if (!parent) continue;
    const from = parent.assigned_agent_id ?? "__none__";
    const to = t.assigned_agent_id ?? "__none__";
    if (from === to) continue;
    const k = `${from}|${to}`;
    if (!edgeSet.has(k)) { edgeSet.add(k); edges.push({ from, to }); }
  }

  // If edges exist, recompute levels via BFS from roots
  if (edges.length > 0) {
    const incomingSet = new Set(edges.map((e) => e.to));
    const roots = Array.from(agentMap.keys()).filter((id) => !incomingSet.has(id));
    const visited = new Set<string>();
    const queue: Array<{ id: string; level: number }> = roots.map((id) => ({ id, level: 0 }));
    while (queue.length) {
      const { id, level } = queue.shift()!;
      if (visited.has(id)) continue;
      visited.add(id);
      const s = agentMap.get(id);
      if (s) s.minDepth = level;
      edges.filter((e) => e.from === id).forEach((e) =>
        queue.push({ id: e.to, level: level + 1 })
      );
    }
  }

  // Group by level
  const byLevel = new Map<number, string[]>();
  for (const [id, s] of Array.from(agentMap.entries())) {
    const l = s.minDepth;
    if (!byLevel.has(l)) byLevel.set(l, []);
    byLevel.get(l)!.push(id);
  }

  const maxLevel = Math.max(...Array.from(byLevel.keys()), 0);
  const maxCols = Math.max(...Array.from(byLevel.values()).map((v) => v.length), 1);
  const w = PAD * 2 + maxCols * NW + Math.max(0, maxCols - 1) * HG;
  const h = PAD * 2 + (maxLevel + 1) * NH + maxLevel * VG;

  const nodes: GNode[] = [];
  const pos = new Map<string, { cx: number; cy: number }>();

  for (const [level, ids] of Array.from(byLevel.entries())) {
    const count = ids.length;
    const span = count * NW + (count - 1) * HG;
    const startX = (w - span) / 2;
    ids.forEach((id: string, col: number) => {
      const x = startX + col * (NW + HG);
      const y = PAD + level * (NH + VG);
      const s = agentMap.get(id)!;
      nodes.push({
        id, name: s.name, agentType: s.agentType, x, y,
        total: s.total, running: s.running, completed: s.completed, failed: s.failed,
      });
      pos.set(id, { cx: x + NW / 2, cy: y + NH / 2 });
    });
  }

  return { nodes, edges, pos, w, h };
}

// ── Status helpers ────────────────────────────────────────────────────────────
function nodeStatus(n: GNode): "running" | "failed" | "completed" | "idle" | "pending" {
  if (n.running > 0) return "running";
  if (n.failed > 0) return "failed";
  if (n.total > 0 && n.completed === n.total) return "completed";
  if (n.total > 0) return "pending";
  return "idle";
}

const STROKE_COLOR: Record<string, string> = {
  running:   "rgba(34,211,238,0.85)",
  failed:    "rgba(248,113,113,0.85)",
  completed: "rgba(74,222,128,0.85)",
  pending:   "rgba(250,204,21,0.6)",
  idle:      "rgba(113,113,122,0.3)",
};
const DOT_COLOR: Record<string, string> = {
  running:   "rgb(34,211,238)",
  failed:    "rgb(248,113,113)",
  completed: "rgb(74,222,128)",
  pending:   "rgb(250,204,21)",
  idle:      "rgba(113,113,122,0.5)",
};

// ── Component ─────────────────────────────────────────────────────────────────
export function AgentGraph({
  tasks,
  allAgents,
  onSelectTask,
  onSelectAgent,
}: {
  tasks: TaskData[];
  allAgents?: KnownAgent[];
  onSelectTask?: (task: TaskData) => void;
  onSelectAgent?: (agentId: string) => void;
}) {
  const { nodes, edges, pos, w, h } = useMemo(
    () => buildGraph(tasks, allAgents),
    [tasks, allAgents]
  );

  if (!nodes.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 select-none">
        <svg width="64" height="64" viewBox="0 0 64 64" style={{ opacity: 0.15 }}>
          <circle cx="16" cy="32" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="48" cy="16" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="48" cy="48" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <line x1="26" y1="28" x2="38" y2="20" stroke="currentColor" strokeWidth="1.5" />
          <line x1="26" y1="36" x2="38" y2="44" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <div className="text-center">
          <p className="text-sm text-muted-foreground">No agents configured</p>
          <p className="text-xs text-muted-foreground/50 mt-1">
            Add agents in Settings to see the topology here
          </p>
        </div>
      </div>
    );
  }

  const handleClick = (nodeId: string) => {
    if (onSelectAgent) {
      onSelectAgent(nodeId);
      return;
    }
    if (!onSelectTask) return;
    const task =
      tasks.find((t) => (t.assigned_agent_id ?? "__none__") === nodeId && t.status === "running") ??
      tasks.find((t) => (t.assigned_agent_id ?? "__none__") === nodeId && t.status !== "completed") ??
      tasks.find((t) => (t.assigned_agent_id ?? "__none__") === nodeId);
    if (task) onSelectTask(task);
  };

  return (
    <div className="w-full h-full overflow-auto flex items-start justify-center p-6">
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        style={{ fontFamily: "inherit", display: "block", flexShrink: 0 }}
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <marker id="ag-tip" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
            <polygon points="0 0, 7 2.5, 0 5" style={{ fill: "rgba(113,113,122,0.4)" }} />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map(({ from, to }) => {
          const f = pos.get(from);
          const t2 = pos.get(to);
          if (!f || !t2) return null;
          const x1 = f.cx, y1 = f.cy + NH / 2;
          const x2 = t2.cx, y2 = t2.cy - NH / 2 - 7;
          const mid = (y1 + y2) / 2;
          return (
            <path
              key={`${from}|${to}`}
              d={`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`}
              fill="none"
              style={{ stroke: "rgba(113,113,122,0.25)", strokeWidth: 1.5 }}
              markerEnd="url(#ag-tip)"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const st = nodeStatus(node);
          const stroke = STROKE_COLOR[st];
          const dot = DOT_COLOR[st];
          const label = node.name.length > 21 ? node.name.slice(0, 19) + "…" : node.name;
          const typeLabel = node.agentType
            ? node.agentType.replace(/_/g, " ")
            : "";
          const sub =
            node.total === 0
              ? typeLabel
              : node.running > 0
              ? `${node.running} running · ${node.total} task${node.total !== 1 ? "s" : ""}`
              : node.completed === node.total
              ? `${node.total} task${node.total !== 1 ? "s" : ""} · done`
              : `${node.total} task${node.total !== 1 ? "s" : ""}`;

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              onClick={() => handleClick(node.id)}
              style={{ cursor: "pointer" }}
            >
              {st === "running" && (
                <rect x={-3} y={-3} width={NW + 6} height={NH + 6} rx={11} ry={11}
                  fill="none"
                  style={{ stroke: "rgba(34,211,238,0.15)", strokeWidth: 2 }}
                />
              )}
              <rect width={NW} height={NH} rx={8} ry={8}
                style={{ fill: "hsl(var(--card))", stroke, strokeWidth: 1.5 }}
              />
              <circle cx={17} cy={NH / 2} r={4.5} style={{ fill: dot }}>
                {st === "running" && (
                  <animate attributeName="opacity" values="1;0.2;1" dur="1.3s" repeatCount="indefinite" />
                )}
              </circle>
              <text x={32} y={NH / 2 - 8} dominantBaseline="middle"
                style={{ fill: "hsl(var(--foreground))", fontSize: 12, fontWeight: 600 }}>
                {label}
              </text>
              <text x={32} y={NH / 2 + 10} dominantBaseline="middle"
                style={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}>
                {sub}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
