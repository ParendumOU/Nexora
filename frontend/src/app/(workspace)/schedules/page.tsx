"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { schedulesApi, agentsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Plus, Trash2, Loader2, Clock, Play, ChevronDown,
  CalendarClock, CheckCircle2, XCircle, RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, PageLoading, PageEmpty,
} from "@/components/layout/page-shell";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Schedule {
  id: string;
  name: string;
  description?: string | null;
  cron_expr?: string | null;
  interval_minutes?: number | null;
  agent_id: string;
  prompt: string;
  is_active: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at: string;
}

interface Agent { id: string; name: string; agent_type: string; }

interface ScheduleRun {
  id: string;
  status: "running" | "completed" | "failed";
  triggered_by: string;
  started_at: string;
  completed_at?: string | null;
  error?: string | null;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CRON_PRESETS = [
  { label: "Every minute",   value: "* * * * *" },
  { label: "Every 5 min",   value: "*/5 * * * *" },
  { label: "Every 15 min",  value: "*/15 * * * *" },
  { label: "Every hour",    value: "0 * * * *" },
  { label: "Daily 9am UTC", value: "0 9 * * *" },
  { label: "Daily midnight",value: "0 0 * * *" },
  { label: "Weekly Mon 9am",value: "0 9 * * 1" },
  { label: "Custom",        value: "custom" },
];

function triggerLabel(s: Schedule) {
  if (s.cron_expr) return s.cron_expr;
  if (s.interval_minutes) {
    const m = s.interval_minutes;
    if (m < 60) return `Every ${m}m`;
    if (m === 60) return "Every hour";
    return `Every ${Math.round(m / 60)}h`;
  }
  return "—";
}

function fmtDate(iso?: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

// ─── Switch ───────────────────────────────────────────────────────────────────

function Switch({ checked, onChange, disabled }: {
  checked: boolean; onChange: () => void; disabled?: boolean;
}) {
  return (
    <button role="switch" aria-checked={checked} disabled={disabled}
      onClick={e => { e.stopPropagation(); onChange(); }}
      className={cn("relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200",
        checked ? "bg-primary" : "bg-muted", disabled && "opacity-50 cursor-not-allowed")}
    >
      <span className={cn("pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200", checked ? "translate-x-4" : "translate-x-0")} />
    </button>
  );
}

// ─── Runs drawer ──────────────────────────────────────────────────────────────

function RunsDialog({ schedule, open, onClose }: { schedule: Schedule; open: boolean; onClose: () => void }) {
  const { data: runs = [], isLoading } = useQuery<ScheduleRun[]>({
    queryKey: ["schedule-runs", schedule.id],
    queryFn: () => schedulesApi.runs(schedule.id).then(r => r.data),
    enabled: open,
    refetchInterval: open ? 5000 : false,
  });

  const statusIcon = (s: ScheduleRun["status"]) => {
    if (s === "running")   return <RotateCcw className="w-3.5 h-3.5 animate-spin text-amber-400" />;
    if (s === "completed") return <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />;
    return <XCircle className="w-3.5 h-3.5 text-destructive" />;
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-sm">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">Run history — {schedule.name}</Dialog.Title>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center h-24 text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin mr-2" />Loading…
              </div>
            ) : runs.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">No runs yet.</p>
            ) : (
              <div className="divide-y divide-border">
                {runs.map(run => (
                  <div key={run.id} className="flex items-start gap-3 px-5 py-3">
                    <div className="mt-0.5">{statusIcon(run.status)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium capitalize">{run.status}</span>
                        <span className="text-[10px] text-muted-foreground">{run.triggered_by}</span>
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {fmtDate(run.started_at)}
                        {run.completed_at && ` → ${fmtDate(run.completed_at)}`}
                      </p>
                      {run.error && (
                        <p className="text-[10px] text-destructive mt-1 font-mono truncate">{run.error}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex justify-end px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Create dialog ────────────────────────────────────────────────────────────

function CreateScheduleDialog({ open, onClose, agents }: {
  open: boolean; onClose: () => void; agents: Agent[];
}) {
  const qc = useQueryClient();
  const [name, setName]             = useState("");
  const [description, setDesc]      = useState("");
  const [agentId, setAgentId]       = useState("");
  const [prompt, setPrompt]         = useState("");
  const [mode, setMode]             = useState<"cron" | "interval">("cron");
  const [cronPreset, setCronPreset] = useState("0 9 * * *");
  const [cronCustom, setCronCustom] = useState("");
  const [interval, setInterval]     = useState("60");

  const cronExpr = cronPreset === "custom" ? cronCustom : cronPreset;

  const create = useMutation({
    mutationFn: () => schedulesApi.create({
      name: name.trim(),
      description: description.trim() || undefined,
      agent_id: agentId,
      prompt: prompt.trim(),
      cron_expr: mode === "cron" ? cronExpr : null,
      interval_minutes: mode === "interval" ? parseInt(interval, 10) : null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      toast.success("Schedule created");
      onClose();
      setName(""); setDesc(""); setAgentId(""); setPrompt("");
      setMode("cron"); setCronPreset("0 9 * * *"); setCronCustom(""); setInterval("60");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to create schedule");
    },
  });

  const canSubmit = name.trim() && agentId && prompt.trim() &&
    (mode === "cron" ? !!cronExpr : parseInt(interval, 10) > 0);

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-sm">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">New Schedule</Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">Run an agent automatically on a schedule</p>
          </div>
          <div className="p-5 space-y-3 max-h-[70vh] overflow-y-auto">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input autoFocus value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" placeholder="Daily briefing" />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Description <span className="opacity-50">(optional)</span></label>
              <Input value={description} onChange={e => setDesc(e.target.value)} className="h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Agent</label>
              <Select.Root value={agentId} onValueChange={setAgentId}>
                <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-sm focus:outline-none">
                  <Select.Value placeholder="Select agent…" />
                  <ChevronDown className="w-3.5 h-3.5 opacity-50" />
                </Select.Trigger>
                <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
                  {agents.map(a => (
                    <Select.Item key={a.id} value={a.id} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                      <Select.ItemText>{a.name}</Select.ItemText>
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Prompt</label>
              <textarea
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                placeholder="Summarize the latest news and send a report…"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Trigger type</label>
              <div className="grid grid-cols-2 gap-1.5">
                {(["cron", "interval"] as const).map(t => (
                  <button key={t} onClick={() => setMode(t)}
                    className={cn("flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-colors capitalize",
                      mode === t ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent")}
                  >
                    <Clock className="w-3.5 h-3.5 shrink-0" />{t === "cron" ? "Cron" : "Interval"}
                  </button>
                ))}
              </div>
            </div>
            {mode === "cron" ? (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-1">
                  {CRON_PRESETS.map(p => (
                    <button key={p.value} onClick={() => setCronPreset(p.value)}
                      className={cn("text-left px-2 py-1.5 rounded text-xs border transition-colors",
                        cronPreset === p.value ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent text-muted-foreground")}
                    >
                      {p.label}
                      {p.value !== "custom" && <span className="ml-1 font-mono opacity-60">{p.value}</span>}
                    </button>
                  ))}
                </div>
                {cronPreset === "custom" && (
                  <div className="space-y-1">
                    <Input value={cronCustom} onChange={e => setCronCustom(e.target.value)} className="h-8 text-sm font-mono" placeholder="*/30 * * * *" />
                    <p className="text-[10px] text-muted-foreground">5-field cron expression (UTC)</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Interval (minutes)</label>
                <Input type="number" min={1} value={interval} onChange={e => setInterval(e.target.value)} className="h-8 text-sm" />
              </div>
            )}
          </div>
          <div className="flex gap-2 justify-end px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" onClick={onClose} disabled={create.isPending}>Cancel</Button>
            <Button size="sm" onClick={() => create.mutate()} disabled={!canSubmit || create.isPending}>
              {create.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}Create
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SchedulesPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [runsSchedule, setRunsSchedule] = useState<Schedule | null>(null);

  const { data: schedules = [], isLoading } = useQuery<Schedule[]>({
    queryKey: ["schedules"],
    queryFn: () => schedulesApi.list().then(r => r.data),
    refetchInterval: 10000,
  });

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });

  const toggleActive = useMutation({
    mutationFn: (s: Schedule) => s.is_active ? schedulesApi.deactivate(s.id) : schedulesApi.activate(s.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to toggle schedule");
    },
  });

  const trigger = useMutation({
    mutationFn: (id: string) => schedulesApi.trigger(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["schedules"] }); toast.success("Schedule triggered"); },
    onError: () => toast.error("Failed to trigger"),
  });

  const del = useMutation({
    mutationFn: (id: string) => schedulesApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["schedules"] }); toast.success("Schedule deleted"); },
    onError: () => toast.error("Delete failed"),
  });

  const agentMap = new Map(agents.map(a => [a.id, a]));

  return (
    <PageShell>
      <PageHeader
        icon={Clock}
        title="Schedules"
        subtitle={`${schedules.length} schedule${schedules.length !== 1 ? "s" : ""} · ${schedules.filter(s => s.is_active).length} active`}
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />New Schedule
          </Button>
        }
      />

      <PageBody>
        {isLoading ? (
          <PageLoading />
        ) : schedules.length === 0 ? (
          <PageEmpty icon={CalendarClock} message="No schedules yet — create one to run an agent automatically">
            <Button size="sm" onClick={() => setCreateOpen(true)}>Create first schedule</Button>
          </PageEmpty>
        ) : (
          <div className="divide-y divide-border">
            {schedules.map(s => {
              const agent = agentMap.get(s.agent_id);
              return (
                <div key={s.id} className="flex items-center gap-4 px-6 py-3.5 hover:bg-accent/10 transition-colors">
                  {/* Icon */}
                  <div className={cn("p-2 rounded-lg border shrink-0",
                    s.is_active
                      ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                      : "text-muted-foreground bg-muted/30 border-border"
                  )}>
                    <Clock className="w-4 h-4" />
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-medium truncate">{s.name}</p>
                      <Badge variant="outline" className="text-[10px] h-4 px-1.5 shrink-0 font-mono">
                        {triggerLabel(s)}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {agent?.name ?? "—"}
                      {s.description && <> · {s.description}</>}
                      {s.next_run_at && (
                        <> · <span className="text-primary/70">next {fmtDate(s.next_run_at)}</span></>
                      )}
                    </p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0" onClick={e => e.stopPropagation()}>
                    {s.is_active && (
                      <span className="flex items-center gap-1 text-[10px] text-green-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />active
                      </span>
                    )}
                    <button
                      onClick={() => setRunsSchedule(s)}
                      title="View run history"
                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <CalendarClock className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => trigger.mutate(s.id)}
                      title="Trigger now"
                      disabled={trigger.isPending}
                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                    >
                      <Play className="w-3.5 h-3.5" />
                    </button>
                    <Switch checked={s.is_active} onChange={() => toggleActive.mutate(s)} disabled={toggleActive.isPending} />
                    <button
                      onClick={() => { if (confirm(`Delete "${s.name}"?`)) del.mutate(s.id); }}
                      className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </PageBody>

      <CreateScheduleDialog open={createOpen} onClose={() => setCreateOpen(false)} agents={agents} />
      {runsSchedule && (
        <RunsDialog schedule={runsSchedule} open={!!runsSchedule} onClose={() => setRunsSchedule(null)} />
      )}
    </PageShell>
  );
}
