"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { Bot, CheckSquare, AlertCircle, List, X, ChevronRight, ChevronDown, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import { chatsApi } from "@/lib/api";
import toast from "react-hot-toast";

export interface ExecNode {
  id: string;
  type: "agent" | "task" | "proposal" | "plan";
  label: string;
  status: string;
  parent_id: string | null;
  entity_id?: string;
  duration_ms?: number;
  token_count?: number;
  proposal_type?: string;
}

interface ExecTree {
  nodes: ExecNode[];
  edges: { source: string; target: string }[];
  chat_id: string;
}

const statusConfig: Record<string, { color: string; dot: string }> = {
  running:   { color: "text-blue-400",  dot: "bg-blue-400 animate-pulse" },
  pending:   { color: "text-gray-400",  dot: "bg-gray-500" },
  completed: { color: "text-green-400", dot: "bg-green-400" },
  failed:    { color: "text-red-400",   dot: "bg-red-400" },
  awaiting:  { color: "text-amber-400", dot: "bg-amber-400 animate-pulse" },
  approved:  { color: "text-green-400", dot: "bg-green-400" },
  rejected:  { color: "text-red-400",   dot: "bg-red-400" },
  auto_approved: { color: "text-green-400", dot: "bg-green-400" },
};

function NodeIcon({ type }: { type: ExecNode["type"] }) {
  const cls = "w-3 h-3 shrink-0 text-muted-foreground";
  switch (type) {
    case "agent":    return <Bot className={cls} />;
    case "task":     return <CheckSquare className={cls} />;
    case "proposal": return <AlertCircle className={cls} />;
    case "plan":     return <List className={cls} />;
  }
}

interface TreeNodeProps {
  node: ExecNode;
  nodes: ExecNode[];
  depth: number;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  expanded: Set<string>;
  toggleExpanded: (id: string) => void;
}

function TreeNode({ node, nodes, depth, onApprove, onReject, expanded, toggleExpanded }: TreeNodeProps) {
  const children = nodes.filter((n) => n.parent_id === node.id);
  const hasChildren = children.length > 0;
  const isExpanded = expanded.has(node.id);
  const sc = statusConfig[node.status] ?? { color: "text-gray-400", dot: "bg-gray-500" };

  return (
    <div style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : "0" }}>
      <div className="flex items-center gap-1.5 py-0.5 group">
        {/* expand/collapse toggle */}
        {hasChildren ? (
          <button
            onClick={() => toggleExpanded(node.id)}
            className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
          >
            {isExpanded
              ? <ChevronDown className="w-3 h-3" />
              : <ChevronRight className="w-3 h-3" />}
          </button>
        ) : (
          <span className="w-3 h-3 shrink-0" />
        )}

        {/* status dot */}
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", sc.dot)} />

        {/* type icon */}
        <NodeIcon type={node.type} />

        {/* label */}
        <span className={cn("text-[11px] truncate max-w-[150px] leading-tight", sc.color)}>
          {node.label}
        </span>

        {/* duration */}
        {node.duration_ms != null && (
          <span className="text-[10px] text-muted-foreground ml-auto shrink-0">
            {(node.duration_ms / 1000).toFixed(1)}s
          </span>
        )}

        {/* proposal approve / reject buttons */}
        {node.type === "proposal" && node.status === "awaiting" && node.entity_id && (
          <div className="flex items-center gap-0.5 ml-auto shrink-0">
            <button
              onClick={() => onApprove(node.entity_id!)}
              className="text-[10px] px-1.5 py-0.5 bg-green-800 hover:bg-green-700 rounded text-green-200 transition-colors"
              title="Approve"
            >
              ✓
            </button>
            <button
              onClick={() => onReject(node.entity_id!)}
              className="text-[10px] px-1.5 py-0.5 bg-red-900 hover:bg-red-800 rounded text-red-200 transition-colors"
              title="Reject"
            >
              ✗
            </button>
          </div>
        )}
      </div>

      {hasChildren && isExpanded && (
        <div className="border-l border-border/50 ml-2">
          {children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              nodes={nodes}
              depth={depth + 1}
              onApprove={onApprove}
              onReject={onReject}
              expanded={expanded}
              toggleExpanded={toggleExpanded}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface Props {
  chatId: string;
  onClose: () => void;
}

export function ExecutionGraphPanel({ chatId, onClose }: Props) {
  const [nodes, setNodes] = useState<ExecNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  // All nodes expanded by default
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  // Expand all nodes whenever we receive a fresh tree
  const handleTree = useCallback((tree: ExecTree) => {
    setNodes(tree.nodes);
    setExpanded(new Set(tree.nodes.map((n) => n.id)));
  }, []);

  useEffect(() => {
    setError(null);
    setConnected(false);

    const url = chatsApi.executionTreeUrl(chatId);
    // Include auth token as query param since EventSource doesn't support headers
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const fullUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url;
    const es = new EventSource(fullUrl);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as ExecTree & { error?: string };
        if (data.error) {
          setError(data.error);
          es.close();
          return;
        }
        handleTree(data);
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [chatId, handleTree]);

  const handleApprove = useCallback(async (proposalId: string) => {
    try {
      await fetch(`/api/proposals/${proposalId}/approve`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
      toast.success("Proposal approved");
      // Tree will refresh on next SSE tick
    } catch {
      toast.error("Failed to approve proposal");
    }
  }, []);

  const handleReject = useCallback(async (proposalId: string) => {
    try {
      await fetch(`/api/proposals/${proposalId}/reject`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
      toast.success("Proposal rejected");
    } catch {
      toast.error("Failed to reject proposal");
    }
  }, []);

  // Build display: roots are nodes with parent_id === null
  const roots = nodes.filter((n) => n.parent_id === null);

  const runningCount = nodes.filter((n) => n.status === "running").length;
  const pendingProposals = nodes.filter((n) => n.type === "proposal" && n.status === "awaiting").length;

  return (
    <div className="flex flex-col h-full w-64 border-l border-border bg-card shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Execution</span>
          {runningCount > 0 && (
            <span className="text-[10px] bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded font-mono">
              {runningCount} running
            </span>
          )}
          {pendingProposals > 0 && (
            <span className="text-[10px] bg-amber-500/15 text-amber-400 px-1.5 py-0.5 rounded font-mono">
              {pendingProposals} awaiting
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full",
              connected ? "bg-green-400" : "bg-yellow-400 animate-pulse"
            )}
            title={connected ? "Live" : "Connecting…"}
          />
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto p-2">
        {error ? (
          <p className="text-xs text-destructive text-center py-8">{error}</p>
        ) : nodes.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-8">
            No execution data yet.
          </p>
        ) : (
          <div className="space-y-0.5">
            {roots.map((root) => (
              <TreeNode
                key={root.id}
                node={root}
                nodes={nodes}
                depth={0}
                onApprove={handleApprove}
                onReject={handleReject}
                expanded={expanded}
                toggleExpanded={toggleExpanded}
              />
            ))}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="px-3 py-2 border-t border-border shrink-0 flex flex-wrap gap-x-3 gap-y-0.5">
        {[
          { status: "running",   label: "Running"  },
          { status: "pending",   label: "Pending"  },
          { status: "completed", label: "Done"     },
          { status: "failed",    label: "Failed"   },
          { status: "awaiting",  label: "Awaiting" },
        ].map(({ status, label }) => {
          const sc = statusConfig[status];
          return (
            <div key={status} className="flex items-center gap-1">
              <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", sc.dot)} />
              <span className="text-[10px] text-muted-foreground">{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
