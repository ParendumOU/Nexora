"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, ChevronDown, ChevronRight, Zap, Clock } from "lucide-react";
import toast from "react-hot-toast";
import { webhookRulesApi, agentsApi } from "@/lib/api";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";

interface WebhookRule {
  id: string;
  source: string;
  event_type: string;
  filter_json: Record<string, unknown> | null;
  agent_id: string;
  task_title_template: string;
  task_description_template: string | null;
  webhook_secret: string | null;
  project_id: string | null;
  is_active: boolean;
  created_at: string;
}

interface TriggerLog {
  id: string;
  rule_id: string;
  event_type: string;
  task_id: string | null;
  payload_summary: Record<string, string> | null;
  created_at: string;
}

interface Agent {
  id: string;
  name: string;
}

const SOURCE_OPTIONS = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "custom", label: "Custom" },
];

const EVENT_TYPES: Record<string, string[]> = {
  github: ["issues.opened", "issues.closed", "issues.reopened", "pull_request.opened", "workflow_run.failed"],
  gitlab: ["issue.opened", "issue.closed", "issue.reopened", "merge_request.opened", "pipeline.failed"],
  custom: [],
};

const SOURCE_COLORS: Record<string, string> = {
  github: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  gitlab: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  custom: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

function RuleFormDialog({
  open,
  rule,
  agents,
  onClose,
}: {
  open: boolean;
  rule: WebhookRule | null;
  agents: Agent[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [source, setSource] = useState(rule?.source ?? "github");
  const [eventType, setEventType] = useState(rule?.event_type ?? "");
  const [agentId, setAgentId] = useState(rule?.agent_id ?? "");
  const [titleTemplate, setTitleTemplate] = useState(rule?.task_title_template ?? "");
  const [descTemplate, setDescTemplate] = useState(rule?.task_description_template ?? "");
  const [filterText, setFilterText] = useState(
    rule?.filter_json ? JSON.stringify(rule.filter_json, null, 2) : ""
  );
  const [secret, setSecret] = useState(rule?.webhook_secret ?? "");
  const [isActive, setIsActive] = useState(rule?.is_active ?? true);
  const [filterError, setFilterError] = useState("");

  const save = useMutation({
    mutationFn: async () => {
      let filter_json: Record<string, unknown> | null = null;
      if (filterText.trim()) {
        try {
          filter_json = JSON.parse(filterText);
        } catch {
          throw new Error("Filter JSON is invalid");
        }
      }
      const payload = {
        source,
        event_type: eventType,
        agent_id: agentId,
        task_title_template: titleTemplate,
        task_description_template: descTemplate || null,
        filter_json,
        webhook_secret: secret || null,
        is_active: isActive,
      };
      if (rule) {
        return webhookRulesApi.update(rule.id, payload);
      }
      return webhookRulesApi.create(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["webhook-rules"] });
      toast.success(rule ? "Rule updated" : "Rule created");
      onClose();
    },
    onError: (e: Error) => {
      if (e.message.includes("JSON")) setFilterError(e.message);
      else toast.error(e.message || "Save failed");
    },
  });

  if (!open) return null;

  const eventOptions = EVENT_TYPES[source] ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-background border border-border rounded-lg w-full max-w-lg shadow-xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-4 border-b border-border shrink-0">
          <h2 className="text-sm font-semibold">{rule ? "Edit rule" : "New automation rule"}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Dispatch a task to an agent when a webhook event fires.</p>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {/* Source + Event */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Source</label>
              <select
                value={source}
                onChange={e => { setSource(e.target.value); setEventType(""); }}
                className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {SOURCE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Event type</label>
              {eventOptions.length > 0 ? (
                <select
                  value={eventType}
                  onChange={e => setEventType(e.target.value)}
                  className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">— select —</option>
                  {eventOptions.map(ev => (
                    <option key={ev} value={ev}>{ev}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={eventType}
                  onChange={e => setEventType(e.target.value)}
                  placeholder="e.g. alert, deploy"
                  className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                />
              )}
            </div>
          </div>

          {/* Agent */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Agent</label>
            <select
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">— select agent —</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          {/* Title template */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Task title template
              <span className="ml-1 font-normal text-muted-foreground/70">— use {"{{event.title}}"}</span>
            </label>
            <input
              type="text"
              value={titleTemplate}
              onChange={e => setTitleTemplate(e.target.value)}
              placeholder="e.g. Fix: {{event.title}}"
              className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Description template */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Task description template
              <span className="ml-1 font-normal text-muted-foreground/70">— optional</span>
            </label>
            <textarea
              value={descTemplate}
              onChange={e => setDescTemplate(e.target.value)}
              rows={3}
              placeholder={"Event: {{event.event_type}}\nURL: {{event.url}}\n\n{{event.description}}"}
              className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary resize-none font-mono"
            />
          </div>

          {/* Filter JSON */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Filter <span className="font-normal text-muted-foreground/70">— JSON, e.g. {"{ \"labels\": [\"bug\"] }"}</span>
            </label>
            <textarea
              value={filterText}
              onChange={e => { setFilterText(e.target.value); setFilterError(""); }}
              rows={2}
              placeholder='{"branch": "main"}'
              className={`w-full text-xs bg-muted/50 border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary resize-none font-mono ${filterError ? "border-destructive" : "border-border"}`}
            />
            {filterError && <p className="text-xs text-destructive">{filterError}</p>}
          </div>

          {/* Secret (custom only) */}
          {source === "custom" && (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Webhook secret</label>
              <input
                type="text"
                value={secret}
                onChange={e => setSecret(e.target.value)}
                placeholder="Used in URL: /api/webhooks/custom/{org_id}/{secret}"
                className="w-full text-xs bg-muted/50 border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary font-mono"
              />
            </div>
          )}

          {/* Active toggle */}
          <label className="flex items-center gap-2 cursor-pointer">
            <div
              onClick={() => setIsActive(v => !v)}
              className={`w-9 h-5 rounded-full transition-colors ${isActive ? "bg-primary" : "bg-muted"}`}
            >
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mt-0.5 ${isActive ? "translate-x-4 ml-0.5" : "translate-x-0.5"}`} />
            </div>
            <span className="text-xs text-muted-foreground">Active</span>
          </label>
        </div>

        <div className="px-5 py-3 border-t border-border flex justify-end gap-2 shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded border border-border hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !eventType || !agentId || !titleTemplate}
            className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : rule ? "Save changes" : "Create rule"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RuleRow({ rule, agents, onEdit, onDelete }: {
  rule: WebhookRule;
  agents: Agent[];
  onEdit: () => void;
  onDelete: () => void;
}) {
  const qc = useQueryClient();
  const [showLog, setShowLog] = useState(false);

  const { data: log = [] } = useQuery<TriggerLog[]>({
    queryKey: ["webhook-rule-log", rule.id],
    queryFn: () => webhookRulesApi.log(rule.id).then(r => r.data),
    enabled: showLog,
  });

  const toggleActive = useMutation({
    mutationFn: () => webhookRulesApi.update(rule.id, { is_active: !rule.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhook-rules"] }),
  });

  const agentName = agents.find(a => a.id === rule.agent_id)?.name ?? rule.agent_id.slice(0, 8);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="flex items-start gap-3 p-3">
        <div
          onClick={() => toggleActive.mutate()}
          className={`mt-0.5 w-8 h-4 rounded-full cursor-pointer shrink-0 transition-colors ${rule.is_active ? "bg-primary" : "bg-muted"}`}
        >
          <div className={`w-3.5 h-3.5 bg-white rounded-full shadow transition-transform mt-0.5 ${rule.is_active ? "translate-x-3.5 ml-0.5" : "translate-x-0.5"}`} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${SOURCE_COLORS[rule.source] ?? "bg-muted text-muted-foreground"}`}>
              {rule.source}
            </span>
            <span className="text-xs font-mono text-foreground">{rule.event_type}</span>
            {rule.filter_json && (
              <span className="text-xs text-muted-foreground font-mono truncate max-w-[160px]">
                {JSON.stringify(rule.filter_json)}
              </span>
            )}
          </div>
          <div className="mt-1 text-xs text-muted-foreground truncate">
            <span className="font-medium text-foreground">{agentName}</span>
            {" · "}
            {rule.task_title_template}
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setShowLog(v => !v)}
            title="Activity log"
            className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted transition-colors"
          >
            {showLog ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          <button onClick={onEdit} className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted transition-colors">
            <Pencil size={13} />
          </button>
          <button onClick={onDelete} className="p-1 text-muted-foreground hover:text-destructive rounded hover:bg-muted transition-colors">
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {showLog && (
        <div className="border-t border-border bg-muted/30 px-3 py-2 space-y-1">
          {log.length === 0 ? (
            <p className="text-xs text-muted-foreground">No triggers yet.</p>
          ) : (
            log.slice(0, 10).map(t => (
              <div key={t.id} className="flex items-center gap-2 text-xs">
                <Clock size={10} className="text-muted-foreground shrink-0" />
                <span className="text-muted-foreground">{new Date(t.created_at).toLocaleString()}</span>
                <span className="font-mono text-foreground">{t.event_type}</span>
                {t.task_id && (
                  <span className="text-muted-foreground truncate">task {t.task_id.slice(0, 8)}</span>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function AutomationsTab() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<WebhookRule | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);

  const { data: rules = [], isLoading } = useQuery<WebhookRule[]>({
    queryKey: ["webhook-rules"],
    queryFn: () => webhookRulesApi.list().then(r => r.data),
  });

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });

  const deleteRule = useMutation({
    mutationFn: (id: string) => webhookRulesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["webhook-rules"] });
      toast.success("Rule deleted");
      setPendingDelete(null);
    },
    onError: () => toast.error("Failed to delete rule"),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Automations</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Dispatch tasks to agents when GitHub, GitLab, or custom webhook events fire.
          </p>
        </div>
        <button
          onClick={() => { setEditing(null); setShowForm(true); }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors"
        >
          <Plus size={12} />
          New rule
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-16 rounded-lg bg-muted/50 animate-pulse" />
          ))}
        </div>
      ) : rules.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Zap size={28} className="text-muted-foreground/40 mb-3" />
          <p className="text-sm font-medium text-muted-foreground">No automation rules yet</p>
          <p className="text-xs text-muted-foreground/70 mt-1 max-w-xs">
            Create rules to automatically dispatch tasks to agents when webhook events arrive.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map(rule => (
            <RuleRow
              key={rule.id}
              rule={rule}
              agents={agents}
              onEdit={() => { setEditing(rule); setShowForm(true); }}
              onDelete={() => setPendingDelete({ id: rule.id, name: `${rule.source} / ${rule.event_type}` })}
            />
          ))}
        </div>
      )}

      {/* Custom webhook URL hint */}
      {rules.some(r => r.source === "custom") && (
        <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 space-y-1">
          <p className="text-xs font-medium">Custom webhook endpoint</p>
          <p className="text-xs text-muted-foreground font-mono break-all">
            POST /api/webhooks/custom/&#123;org_id&#125;/&#123;secret&#125;
          </p>
          <p className="text-xs text-muted-foreground">
            Send JSON with an <code className="bg-muted px-1 rounded">event_type</code> field. The secret matches the rule{"'"}s webhook secret.
          </p>
        </div>
      )}

      <RuleFormDialog
        open={showForm}
        rule={editing}
        agents={agents}
        onClose={() => { setShowForm(false); setEditing(null); }}
      />

      <ConfirmDeleteDialog
        open={!!pendingDelete}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteRule.mutate(pendingDelete.id)}
        loading={deleteRule.isPending}
        title="Delete rule?"
        description={`"${pendingDelete?.name}" will be permanently removed.`}
        destroys={["This automation rule", "All trigger history for this rule"]}
      />
    </div>
  );
}
