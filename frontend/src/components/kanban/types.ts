export type Priority = "low" | "medium" | "high" | "critical";

export type KanbanTask = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: Priority;
  blocked_by: string[];
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  checklist: { id: string; item: string; done: boolean }[];
  chat_id: string;
  sub_chat_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type BoardColumns = Record<string, KanbanTask[]>;

export const COLUMN_ORDER = [
  "pending",
  "queued",
  "running",
  "paused",
  "completed",
  "failed",
] as const;

export type ColumnId = (typeof COLUMN_ORDER)[number];

export const COLUMN_CONFIG: Record<ColumnId, { label: string; dot: string; border: string }> = {
  pending:   { label: "Pending",     dot: "bg-yellow-400", border: "border-yellow-400/20" },
  queued:    { label: "Queued",      dot: "bg-blue-400",   border: "border-blue-400/20"   },
  running:   { label: "In Progress", dot: "bg-cyan-400",   border: "border-cyan-400/20"   },
  paused:    { label: "Paused",      dot: "bg-orange-400", border: "border-orange-400/20" },
  completed: { label: "Done",        dot: "bg-green-400",  border: "border-green-400/20"  },
  failed:    { label: "Failed",      dot: "bg-red-400",    border: "border-red-400/20"    },
};

export const PRIORITY_CONFIG: Record<Priority, { label: string; className: string }> = {
  low:      { label: "Low",      className: "bg-slate-400/15 text-slate-400"   },
  medium:   { label: "Medium",   className: "bg-blue-400/15 text-blue-400"     },
  high:     { label: "High",     className: "bg-orange-400/15 text-orange-400" },
  critical: { label: "Critical", className: "bg-red-400/15 text-red-400"       },
};
