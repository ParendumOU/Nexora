"use client";

import { use, useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from "@xyflow/react";
import type { Node, Edge, NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { chatsApi } from "@/lib/api";
import {
  Loader2,
  Network,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Search,
  Eye,
  EyeOff,
  X as XIcon,
  StopCircle,
  LayoutGrid,
  GitBranch,
  ExternalLink,
  ArrowUpRight,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TaskCounts {
  total: number;
  running: number;
  failed: number;
  completed: number;
  pending: number;
  queued: number;
  paused: number;
}

type NodeType = "ancestor" | "current" | "descendant";
type NodeStatus = "running" | "failed" | "completed" | "stalled" | "idle";

// Plain API shape — concrete types, no ReactFlow index-signature bleed
interface ApiNode {
  id: string;
  title: string;
  agent_name: string | null;
  parent_chat_id: string | null;
  depth: number;
  node_type: NodeType;
  status: NodeStatus;
  task_counts: TaskCounts;
}

// ReactFlow data must extend Record<string, unknown>
interface ChatNodeData extends Record<string, unknown> {
  id: string;
  title: string;
  agent_name: string | null;
  depth: number;
  node_type: NodeType;
  status: NodeStatus;
  task_counts: TaskCounts;
  isCurrentChat: boolean;
  isSelected: boolean;
}

interface HierarchyResponse {
  root_id: string;
  anchor_id: string;
  nodes: ApiNode[];
  edges: { source: string; target: string }[];
}

type ChatFlowNode = Node<ChatNodeData, "chatNode">;

// ── Status palette ────────────────────────────────────────────────────────────

const STATUS: Record<
  string,
  { border: string; glow: string; dot: string; label: string; bg: string }
> = {
  running:   { border: "border-cyan-500",   glow: "shadow-cyan-500/25",  dot: "bg-cyan-400 animate-pulse", label: "Running",   bg: "bg-cyan-500/10" },
  failed:    { border: "border-red-500",    glow: "shadow-red-500/25",   dot: "bg-red-400",                label: "Failed",    bg: "bg-red-500/10" },
  completed: { border: "border-green-500",  glow: "shadow-green-500/25", dot: "bg-green-400",              label: "Completed", bg: "bg-green-500/10" },
  stalled:   { border: "border-orange-500", glow: "shadow-orange-500/25",dot: "bg-orange-400",             label: "Stalled",   bg: "bg-orange-500/10" },
  idle:      { border: "border-border",     glow: "",                    dot: "bg-muted-foreground",       label: "Idle",      bg: "bg-card" },
};

// ── Custom node ───────────────────────────────────────────────────────────────

function ChatNode({ data }: NodeProps<ChatFlowNode>) {
  const d = data as ChatNodeData;
  const s = STATUS[d.status] ?? STATUS.idle;
  const isAncestor  = d.node_type === "ancestor";
  const isCurrent   = d.node_type === "current";
  const tc = d.task_counts;

  const ringClass = d.isCurrentChat
    ? "ring-2 ring-primary ring-offset-2 ring-offset-background"
    : d.isSelected
    ? "ring-2 ring-white/30 ring-offset-1 ring-offset-background"
    : "";

  if (isAncestor) {
    // Minimalist ancestor: smaller, ghost style, just title + agent
    return (
      <div
        onClick={() => window.open(`/chat/${d.id}`, "_blank")}
        className={`w-44 rounded-lg border border-dashed border-border/60 bg-background/50 px-3 py-2 cursor-pointer opacity-70 hover:opacity-100 transition-opacity ${ringClass}`}
      >
        <Handle type="target" position={Position.Top}   style={{ opacity: 0, pointerEvents: "none" }} />
        <div className="flex items-center gap-2">
          <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
          <p className="text-[11px] font-medium text-muted-foreground leading-snug truncate">
            {d.title}
          </p>
        </div>
        {d.agent_name && (
          <p className="text-[9px] text-muted-foreground/60 mt-0.5 truncate pl-3.5">
            {d.agent_name}
          </p>
        )}
        <Handle type="source" position={Position.Bottom} style={{ opacity: 0, pointerEvents: "none" }} />
      </div>
    );
  }

  return (
    <div
      onClick={() => window.open(`/chat/${d.id}`, "_blank")}
      className={`w-52 rounded-xl border-2 ${s.bg} p-3 cursor-pointer shadow-lg hover:shadow-xl transition-all hover:scale-[1.02] ${s.border} ${s.glow} ${ringClass}`}
    >
      <Handle type="target" position={Position.Top}   style={{ opacity: 0, pointerEvents: "none" }} />
      <div className="flex items-start gap-2">
        <div className={`mt-[3px] w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-foreground leading-snug line-clamp-2">
            {d.title}
          </p>
          {d.agent_name && (
            <p className="text-[10px] text-muted-foreground mt-0.5 truncate">{d.agent_name}</p>
          )}
        </div>
        {isCurrent && (
          <span className="shrink-0 text-[9px] font-mono bg-primary/20 text-primary px-1 py-0.5 rounded">
            HERE
          </span>
        )}
      </div>
      {tc.total > 0 && (
        <div className="mt-2 pt-2 border-t border-border/50 flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>{tc.completed}/{tc.total} done</span>
          {tc.running > 0 && <span className="text-cyan-400">{tc.running} active</span>}
          {tc.failed  > 0 && <span className="text-red-400">{tc.failed} failed</span>}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, pointerEvents: "none" }} />
    </div>
  );
}

const nodeTypes = { chatNode: ChatNode };

// ── Layout ────────────────────────────────────────────────────────────────────

const NODE_W  = 208;
const ANC_W   = 176;
const NODE_H  = 110;
const ANC_H   = 58;
const X_GAP   = 32;
const Y_GAP   = 60;
const ANC_GAP = 40;

// ── Layout mode ───────────────────────────────────────────────────────────────
type LayoutMode = "compact" | "tree";

function layoutCompact(
  apiNodes: ApiNode[],
  posCache?: Map<string, { x: number; y: number }>,
): ChatFlowNode[] {
  const ancestors   = apiNodes.filter((n) => n.depth < 0).sort((a, b) => a.depth - b.depth);
  const anchor      = apiNodes.find((n) => n.depth === 0);
  const descendants = apiNodes.filter((n) => n.depth > 0);

  const byDepth = new Map<number, ApiNode[]>();
  for (const n of descendants) {
    if (!byDepth.has(n.depth)) byDepth.set(n.depth, []);
    byDepth.get(n.depth)!.push(n);
  }

  let maxItems = 1;
  for (const items of Array.from(byDepth.values())) {
    if (items.length > maxItems) maxItems = items.length;
  }
  const canvasW = maxItems * NODE_W + (maxItems - 1) * X_GAP;
  const centerX = canvasW / 2;

  const result: ChatFlowNode[] = [];

  let y = -(ancestors.length) * (ANC_H + ANC_GAP);
  for (const node of ancestors) {
    result.push({
      id: node.id, type: "chatNode",
      position: posCache?.get(node.id) ?? { x: centerX - ANC_W / 2, y },
      data: { ...node, isCurrentChat: false, isSelected: false },
    });
    y += ANC_H + ANC_GAP;
  }

  if (anchor) {
    result.push({
      id: anchor.id, type: "chatNode",
      position: posCache?.get(anchor.id) ?? { x: centerX - NODE_W / 2, y: 0 },
      data: { ...anchor, isCurrentChat: false, isSelected: false },
    });
  }

  for (const [depth, items] of Array.from(byDepth.entries())) {
    const levelW = items.length * NODE_W + (items.length - 1) * X_GAP;
    const startX = (canvasW - levelW) / 2;
    items.forEach((node, idx) => {
      result.push({
        id: node.id, type: "chatNode",
        position: posCache?.get(node.id) ?? {
          x: startX + idx * (NODE_W + X_GAP),
          y: depth * (NODE_H + Y_GAP),
        },
        data: { ...node, isCurrentChat: false, isSelected: false },
      });
    });
  }

  return result;
}

function layoutTree(
  apiNodes: ApiNode[],
  posCache?: Map<string, { x: number; y: number }>,
): ChatFlowNode[] {
  const ancestors   = apiNodes.filter((n) => n.depth < 0).sort((a, b) => a.depth - b.depth);
  const anchor      = apiNodes.find((n) => n.depth === 0);
  const descendants = apiNodes.filter((n) => n.depth > 0);

  const nodeById   = new Map(apiNodes.map((n) => [n.id, n]));
  const childrenOf = new Map<string, ApiNode[]>();
  for (const n of descendants) {
    const pid = (n.parent_chat_id && nodeById.has(n.parent_chat_id))
      ? n.parent_chat_id
      : anchor?.id ?? "";
    if (!childrenOf.has(pid)) childrenOf.set(pid, []);
    childrenOf.get(pid)!.push(n);
  }

  const subtreeW = new Map<string, number>();
  function getW(id: string): number {
    if (subtreeW.has(id)) return subtreeW.get(id)!;
    const kids = childrenOf.get(id) ?? [];
    const w = kids.length === 0
      ? NODE_W
      : kids.reduce((s, k, i) => s + getW(k.id) + (i > 0 ? X_GAP : 0), 0);
    subtreeW.set(id, Math.max(NODE_W, w));
    return subtreeW.get(id)!;
  }
  if (anchor) getW(anchor.id);

  const computed = new Map<string, { x: number; y: number }>();
  function place(nodeId: string, cx: number, y: number) {
    computed.set(nodeId, { x: cx - NODE_W / 2, y });
    const kids = childrenOf.get(nodeId) ?? [];
    if (!kids.length) return;
    const childY = y + NODE_H + Y_GAP;
    const totalW = kids.reduce((s, k, i) => s + getW(k.id) + (i > 0 ? X_GAP : 0), 0);
    let xCursor  = cx - totalW / 2;
    for (const kid of kids) {
      const sw = getW(kid.id);
      place(kid.id, xCursor + sw / 2, childY);
      xCursor += sw + X_GAP;
    }
  }
  if (anchor) place(anchor.id, 0, 0);

  const result: ChatFlowNode[] = [];
  const anchorPos = posCache?.get(anchor?.id ?? "") ?? computed.get(anchor?.id ?? "") ?? { x: -NODE_W / 2, y: 0 };
  const anchorCX  = anchorPos.x + NODE_W / 2;

  let y = -(ancestors.length) * (ANC_H + ANC_GAP);
  for (const node of ancestors) {
    result.push({
      id: node.id, type: "chatNode",
      position: posCache?.get(node.id) ?? { x: anchorCX - ANC_W / 2, y },
      data: { ...node, isCurrentChat: false, isSelected: false },
    });
    y += ANC_H + ANC_GAP;
  }

  if (anchor) {
    result.push({
      id: anchor.id, type: "chatNode",
      position: anchorPos,
      data: { ...anchor, isCurrentChat: false, isSelected: false },
    });
  }

  for (const n of descendants) {
    result.push({
      id: n.id, type: "chatNode",
      position: posCache?.get(n.id) ?? computed.get(n.id) ?? { x: 0, y: n.depth * (NODE_H + Y_GAP) },
      data: { ...n, isCurrentChat: false, isSelected: false },
    });
  }

  return result;
}

function computeLayout(
  apiNodes: ApiNode[],
  mode: LayoutMode,
  posCache?: Map<string, { x: number; y: number }>,
): ChatFlowNode[] {
  return mode === "tree" ? layoutTree(apiNodes, posCache) : layoutCompact(apiNodes, posCache);
}

// ── Sidebar tree helpers ──────────────────────────────────────────────────────

interface TreeNode {
  node: ApiNode;
  children: TreeNode[];
}

function buildTree(nodes: ApiNode[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const n of nodes) byId.set(n.id, { node: n, children: [] });
  const roots: TreeNode[] = [];
  for (const n of nodes) {
    const tn = byId.get(n.id)!;
    const parentInSet = n.parent_chat_id && byId.has(n.parent_chat_id);
    if (parentInSet) {
      byId.get(n.parent_chat_id!)!.children.push(tn);
    } else {
      roots.push(tn);
    }
  }
  return roots;
}

function SidebarTreeNode({
  tn,
  depth,
  collapsed,
  toggleCollapse,
  selectedNodeId,
  focusNode,
}: {
  tn: TreeNode;
  depth: number;
  collapsed: Set<string>;
  toggleCollapse: (id: string) => void;
  selectedNodeId: string | null;
  focusNode: (id: string) => void;
}) {
  const { node } = tn;
  const s = STATUS[node.status] ?? STATUS.idle;
  const tc = node.task_counts;
  const isSelected = node.id === selectedNodeId;
  const isCurrent  = node.node_type === "current";
  const hasChildren = tn.children.length > 0;
  const isCollapsed = collapsed.has(node.id);

  return (
    <div>
      <div
        className={`flex items-center border-b border-border/40 transition-colors ${
          isSelected ? "bg-accent" : "hover:bg-accent/50"
        }`}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
      >
        {/* Collapse toggle */}
        <button
          onClick={() => hasChildren && toggleCollapse(node.id)}
          className={`p-1 shrink-0 ${hasChildren ? "text-muted-foreground hover:text-foreground" : "opacity-0 pointer-events-none"}`}
        >
          {isCollapsed
            ? <ChevronRight className="w-3 h-3" />
            : <ChevronDown  className="w-3 h-3" />}
        </button>

        {/* Row content */}
        <button
          onClick={() => focusNode(node.id)}
          className="flex-1 flex items-start gap-1.5 py-2 pr-2 min-w-0 text-left"
        >
          <div className={`mt-[3px] w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
          <div className="flex-1 min-w-0">
            <p className={`text-xs font-medium leading-snug truncate ${isCurrent ? "text-primary" : "text-foreground"}`}>
              {node.title}
            </p>
            {node.agent_name && (
              <p className="text-[10px] text-muted-foreground truncate mt-0.5">{node.agent_name}</p>
            )}
          </div>
          {tc.total > 0 && (
            <span className="text-[10px] text-muted-foreground font-mono shrink-0 mt-0.5">
              {tc.completed}/{tc.total}
            </span>
          )}
        </button>
      </div>

      {/* Children */}
      {hasChildren && !isCollapsed && (
        <div>
          {tn.children.map((child) => (
            <SidebarTreeNode
              key={child.node.id}
              tn={child}
              depth={depth + 1}
              collapsed={collapsed}
              toggleCollapse={toggleCollapse}
              selectedNodeId={selectedNodeId}
              focusNode={focusNode}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main content ──────────────────────────────────────────────────────────────

function HierarchyContent({ chatId }: { chatId: string }) {
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState<string | null>(null);
  const [rootId, setRootId]             = useState<string | null>(null);
  const [searchQuery, setSearchQuery]   = useState("");
  const [hideFinished, setHideFinished] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [allApiNodes, setAllApiNodes]   = useState<ApiNode[]>([]);
  const [collapsed, setCollapsed]       = useState<Set<string>>(new Set());
  const [killing, setKilling]           = useState(false);
  const [layoutMode, setLayoutMode]     = useState<LayoutMode>("compact");
  const allEdgesRef    = useRef<Edge[]>([]);                            // never mutated by filters
  const positionCache  = useRef<Map<string, { x: number; y: number }>>(new Map()); // preserves user/layout positions
  const prevCountRef   = useRef(0);                                     // track when new nodes arrive
  const pollCallbackRef = useRef<(() => Promise<void>) | undefined>(undefined); // always-fresh poll fn ref
  const initialLoaded  = useRef(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<ChatFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { setCenter, fitView }           = useReactFlow();

  // Load
  useEffect(() => {
    chatsApi.hierarchy(chatId).then((r) => {
      const data: HierarchyResponse = r.data;
      setRootId(data.root_id);
      setAllApiNodes(data.nodes);

      const flowNodes = computeLayout(data.nodes, "compact").map((n) => ({
        ...n,
        data: { ...n.data, isCurrentChat: n.id === chatId },
      }));
      const flowEdges: Edge[] = data.edges.map((e) => ({
        id:     `${e.source}→${e.target}`,
        source: e.source,
        target: e.target,
        type:   "smoothstep",
        style:  { stroke: "hsl(var(--border))", strokeWidth: 1.5 },
      }));
      allEdgesRef.current = flowEdges;
      prevCountRef.current = data.nodes.length;
      initialLoaded.current = true;
      setNodes(flowNodes);
      setEdges(flowEdges);
    })
    .catch(() => setError("Failed to load hierarchy."))
    .finally(() => setLoading(false));
  }, [chatId]);

  // Sync isSelected
  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => ({ ...n, data: { ...n.data, isSelected: n.id === selectedNodeId } }))
    );
  }, [selectedNodeId]);

  // Ancestors are never hidden — only descendants can be filtered
  const filteredApiNodes = useMemo(() => {
    const allById = new Map(allApiNodes.map((n) => [n.id, n]));

    // Step 1: basic status + search filter
    let result = allApiNodes.filter((n) => {
      if (n.node_type === "ancestor" || n.node_type === "current") return true;
      if (hideFinished && ["completed", "failed"].includes(n.status)) return false;
      if (searchQuery.trim()) {
        return n.title.toLowerCase().includes(searchQuery.toLowerCase());
      }
      return true;
    });

    // Step 2: reinsert any intermediary nodes needed to keep the tree connected.
    // For each surviving node, walk parent_chat_id up through allApiNodes;
    // if a parent is missing from the result set, add it back as a bridge.
    if (hideFinished || searchQuery.trim()) {
      const resultIds = new Set(result.map((n) => n.id));
      const toAdd: ApiNode[] = [];

      for (const node of result) {
        let parentId = node.parent_chat_id;
        while (parentId && !resultIds.has(parentId)) {
          const parent = allById.get(parentId);
          if (!parent) break;
          toAdd.push(parent);
          resultIds.add(parentId);
          parentId = parent.parent_chat_id;
        }
      }

      if (toAdd.length > 0) {
        result = [...result, ...toAdd];
        // Re-sort by depth so layout gets consistent ordering
        result.sort((a, b) => a.depth - b.depth);
      }
    }

    return result;
  }, [allApiNodes, hideFinished, searchQuery]);

  const visibleIds = useMemo(
    () => new Set(filteredApiNodes.map((n) => n.id)),
    [filteredApiNodes]
  );

  // When the user toggles a filter, clear the position cache so nodes reorganize
  // from scratch. This effect must appear BEFORE the layout effect so React runs
  // it first within the same render cycle.
  const shouldFitRef = useRef(false);
  useEffect(() => {
    positionCache.current = new Map();
    shouldFitRef.current = true;
  }, [hideFinished, searchQuery, layoutMode]);

  // Re-compute layout & edges when filter changes (or when allApiNodes updates from poll)
  useEffect(() => {
    if (allApiNodes.length === 0 || !initialLoaded.current) return;

    // When new nodes arrive, clear the position cache so the whole tree reorganises
    // cleanly using the tree algorithm instead of stale flat-layout coordinates.
    const isNewNodes = filteredApiNodes.length > prevCountRef.current;
    prevCountRef.current = filteredApiNodes.length;
    if (isNewNodes) {
      positionCache.current = new Map();
      shouldFitRef.current = true;
    }

    const flowNodes = computeLayout(filteredApiNodes, layoutMode, positionCache.current).map((n) => ({
      ...n,
      data: {
        ...n.data,
        isCurrentChat: n.id === chatId,
        isSelected:    n.id === selectedNodeId,
      },
    }));
    // Seed cache with computed positions for nodes not yet cached
    for (const fn of flowNodes) {
      if (!positionCache.current.has(fn.id)) {
        positionCache.current.set(fn.id, fn.position);
      }
    }
    setNodes(flowNodes);
    setEdges(allEdgesRef.current.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target)
    ));
    if (isNewNodes || shouldFitRef.current) {
      shouldFitRef.current = false;
      const timer = setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 60);
      return () => clearTimeout(timer);
    }
  }, [filteredApiNodes, layoutMode]);

  // Status counts (descendants only)
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of allApiNodes) {
      if (n.node_type === "ancestor") continue;
      counts[n.status] = (counts[n.status] ?? 0) + 1;
    }
    return counts;
  }, [allApiNodes]);

  const descendants    = useMemo(() => allApiNodes.filter((n) => n.node_type !== "ancestor"), [allApiNodes]);
  const visibleDescend = useMemo(() => filteredApiNodes.filter((n) => n.node_type !== "ancestor"), [filteredApiNodes]);
  const ancestors      = useMemo(() => allApiNodes.filter((n) => n.node_type === "ancestor").sort((a, b) => a.depth - b.depth), [allApiNodes]);

  // Keep position cache in sync when user drags nodes
  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes);
      for (const change of changes) {
        if (change.type === "position" && change.position) {
          positionCache.current.set(change.id, change.position);
        }
      }
    },
    [onNodesChange]
  );

  // ── Live polling ──────────────────────────────────────────────────────────
  // Keep a fresh ref to the poll function so the interval never needs recreating
  useEffect(() => {
    pollCallbackRef.current = async () => {
      if (!initialLoaded.current) return;
      try {
        const r = await chatsApi.hierarchy(chatId);
        const data: HierarchyResponse = r.data;

        // Merge new edges into allEdgesRef
        const existingEdgeIds = new Set(allEdgesRef.current.map((e) => e.id));
        const freshEdges: Edge[] = data.edges
          .map((e) => ({
            id:     `${e.source}→${e.target}`,
            source: e.source,
            target: e.target,
            type:   "smoothstep" as const,
            style:  { stroke: "hsl(var(--border))", strokeWidth: 1.5 },
          }))
          .filter((e) => !existingEdgeIds.has(e.id));
        if (freshEdges.length > 0) {
          allEdgesRef.current = [...allEdgesRef.current, ...freshEdges];
        }

        // Update allApiNodes — triggers filteredApiNodes recompute → layout effect
        // Position cache ensures existing nodes don't jump
        setAllApiNodes(data.nodes);
      } catch {
        // ignore transient poll errors
      }
    };
  });

  useEffect(() => {
    const id = setInterval(() => pollCallbackRef.current?.(), 4000);
    return () => clearInterval(id);
  }, []);

  const toggleCollapse = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const sidebarTree = useMemo(() => buildTree(visibleDescend), [visibleDescend]);

  const focusNode = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      if (!node) return;
      setCenter(node.position.x + NODE_W / 2, node.position.y + NODE_H / 2, {
        zoom: 1.2, duration: 500,
      });
      setSelectedNodeId(nodeId);
    },
    [nodes, setCenter]
  );

  if (loading) return (
    <div className="flex h-screen items-center justify-center bg-background">
      <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
    </div>
  );

  if (error) return (
    <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      {error}
    </div>
  );

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border shrink-0">
        <Network className="w-4 h-4 text-muted-foreground" />
        <span className="text-sm font-semibold">Conversation Hierarchy</span>
        <span className="text-[10px] font-mono bg-accent text-muted-foreground px-1.5 py-0.5 rounded">
          {descendants.length} conversations
        </span>

        {/* Selected-node actions */}
        {selectedNodeId && (() => {
          const sel = allApiNodes.find((n) => n.id === selectedNodeId);
          const parentId = sel?.parent_chat_id;
          return (
            <>
              <div className="w-px h-4 bg-border mx-1" />
              <button
                onClick={() => window.open(`/chat/${selectedNodeId}`, "_blank")}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                title="Open selected conversation"
              >
                <ExternalLink className="w-3 h-3" />
                Open
              </button>
              {parentId && (
                <button
                  onClick={() => window.open(`/chat/${parentId}`, "_blank")}
                  className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                  title="Open parent conversation"
                >
                  <ArrowUpRight className="w-3 h-3" />
                  Parent
                </button>
              )}
            </>
          );
        })()}

        <div className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
          {Object.entries(STATUS).map(([key, s]) =>
            statusCounts[key] ? (
              <div key={key} className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${s.dot.replace(" animate-pulse", "")}`} />
                <span>{statusCounts[key]} {s.label}</span>
              </div>
            ) : null
          )}
          <div className="flex items-center rounded border border-border overflow-hidden">
            <button
              onClick={() => setLayoutMode("compact")}
              className={`flex items-center gap-1.5 px-2.5 py-1 transition-colors ${
                layoutMode === "compact" ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50"
              }`}
              title="Compact"
            >
              <LayoutGrid className="w-3 h-3" />
              Compact
            </button>
            <div className="w-px h-4 bg-border" />
            <button
              onClick={() => setLayoutMode("tree")}
              className={`flex items-center gap-1.5 px-2.5 py-1 transition-colors ${
                layoutMode === "tree" ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50"
              }`}
              title="Tree"
            >
              <GitBranch className="w-3 h-3" />
              Tree
            </button>
          </div>
          <button
            onClick={async () => {
              if (!window.confirm("Cancel all active tasks in this hierarchy?")) return;
              setKilling(true);
              try { await chatsApi.cancelAll(rootId ?? chatId); }
              finally { setKilling(false); }
            }}
            disabled={killing}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
          >
            <StopCircle className="w-3 h-3" />
            {killing ? "Cancelling…" : "Kill All"}
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <div className="w-64 border-r border-border flex flex-col bg-card shrink-0 overflow-hidden">

          {/* Back to PM Chat */}
          {rootId && rootId !== chatId && (
            <button
              onClick={() => window.open(`/chat/${rootId}`, "_blank")}
              className="flex items-center gap-2 px-3 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors border-b border-border w-full text-left shrink-0"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Back to PM Chat</span>
            </button>
          )}

          {/* Ancestor path */}
          {ancestors.length > 0 && (
            <div className="shrink-0 border-b border-border">
              <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
                Path from PM
              </div>
              {ancestors.map((node, idx) => {
                const s = STATUS[node.status] ?? STATUS.idle;
                return (
                  <button
                    key={node.id}
                    onClick={() => focusNode(node.id)}
                    className="w-full text-left py-1.5 pr-3 hover:bg-accent/40 transition-colors"
                    style={{ paddingLeft: `${12 + idx * 10}px` }}
                  >
                    <div className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
                      <p className="text-[11px] text-muted-foreground truncate">{node.title}</p>
                    </div>
                  </button>
                );
              })}
              {/* Arrow connector into current */}
              <div className="flex items-center px-3 py-0.5">
                <div className="ml-[15px] w-px h-3 bg-border/60" />
              </div>
            </div>
          )}

          {/* Search */}
          <div className="px-3 py-2 border-b border-border shrink-0">
            <div className="flex items-center gap-2 bg-background border border-border rounded px-2 py-1.5">
              <Search className="w-3 h-3 text-muted-foreground shrink-0" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search conversations…"
                className="flex-1 bg-transparent text-xs outline-none text-foreground placeholder:text-muted-foreground min-w-0"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} className="text-muted-foreground hover:text-foreground shrink-0">
                  <XIcon className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Show/hide toggle */}
          <button
            onClick={() => setHideFinished((h) => !h)}
            className={`flex items-center justify-between px-3 py-2 text-xs border-b border-border transition-colors shrink-0 w-full ${
              hideFinished ? "text-foreground bg-accent/60" : "text-muted-foreground hover:bg-accent/40"
            }`}
          >
            <div className="flex items-center gap-2">
              {hideFinished ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              <span>{hideFinished ? "Active only" : "Showing all"}</span>
            </div>
            <span className="text-[10px] font-mono bg-background border border-border px-1.5 py-0.5 rounded">
              {visibleDescend.length}/{descendants.length}
            </span>
          </button>

          {/* Conversation list (descendants only) — collapsible tree */}
          <div className="flex-1 overflow-y-auto">
            {sidebarTree.length === 0 ? (
              <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                No conversations match
              </div>
            ) : (
              sidebarTree.map((tn) => (
                <SidebarTreeNode
                  key={tn.node.id}
                  tn={tn}
                  depth={0}
                  collapsed={collapsed}
                  toggleCollapse={toggleCollapse}
                  selectedNodeId={selectedNodeId}
                  focusNode={focusNode}
                />
              ))
            )}
          </div>
        </div>

        {/* ── Graph ── */}
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15, maxZoom: 1.2 }}
            minZoom={0.05}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="hsl(var(--border))" gap={24} size={1} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const colors: Record<string, string> = {
                  running:   "#22d3ee",
                  failed:    "#ef4444",
                  completed: "#22c55e",
                  stalled:   "#f97316",
                  idle:      "#6b7280",
                };
                const nd = n.data as ChatNodeData;
                if (nd.node_type === "ancestor") return "#374151";
                return colors[nd.status] ?? "#6b7280";
              }}
              maskColor="rgba(0,0,0,0.4)"
              style={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))" }}
            />
          </ReactFlow>
        </div>
      </div>
    </div>
  );
}

// ── Page wrapper ──────────────────────────────────────────────────────────────

export default function HierarchyPage({ params }: { params: Promise<{ chatId: string }> }) {
  const { chatId } = use(params);
  return (
    <ReactFlowProvider>
      <HierarchyContent chatId={chatId} />
    </ReactFlowProvider>
  );
}
