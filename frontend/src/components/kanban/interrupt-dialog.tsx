"use client";
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, Loader2, StopCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentsApi, tasksApi } from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { KanbanTask } from "./types";

type Agent = { id: string; name: string; description?: string };

type Props = {
  task: KanbanTask | null;
  projectId: string;
  onClose: () => void;
};

export function InterruptDialog({ task, projectId, onClose }: Props) {
  const qc = useQueryClient();
  const [reassignAgentId, setReassignAgentId] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const { data: agents } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
    enabled: !!task,
  });

  const otherAgents = (agents ?? []).filter(
    (a) => a.id !== task?.assigned_agent_id
  );

  async function handleConfirm(withReassign: boolean) {
    if (!task) return;
    setLoading(true);
    try {
      await tasksApi.interrupt(task.id, {
        reassign_to_agent_id: withReassign && reassignAgentId ? reassignAgentId : null,
      });
      qc.invalidateQueries({ queryKey: ["board", projectId] });
      onClose();
    } finally {
      setLoading(false);
    }
  }

  const isRunning = task?.status === "in_progress" || task?.status === "running" || task?.status === "queued";

  return (
    <Dialog.Root open={!!task} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-full max-w-md bg-card border border-border rounded-xl shadow-lg p-5 space-y-4 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-full bg-orange-500/10 shrink-0 mt-0.5">
              <StopCircle className="w-4 h-4 text-orange-500" />
            </div>
            <div>
              <Dialog.Title className="text-sm font-semibold">Interrupt task</Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {isRunning
                  ? "A stop signal will be sent. The agent will halt at its next checkpoint."
                  : "The task will be stopped before it starts."}
              </Dialog.Description>
            </div>
          </div>

          <div className="bg-muted/40 border border-border/60 rounded-lg px-3 py-2.5">
            <p className="text-xs font-medium truncate">{task?.title}</p>
            {task?.assigned_agent_name && (
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Currently assigned to: <span className="font-medium">{task.assigned_agent_name}</span>
              </p>
            )}
          </div>

          {otherAgents.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 text-muted-foreground" />
                <p className="text-xs font-medium">Reassign to a different agent (optional)</p>
              </div>
              <div className="grid gap-1.5 max-h-40 overflow-y-auto pr-1">
                <label
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer text-xs transition-colors ${
                    reassignAgentId === ""
                      ? "border-border bg-muted/30 text-foreground"
                      : "border-transparent text-muted-foreground hover:border-border/60"
                  }`}
                >
                  <input
                    type="radio"
                    name="agent"
                    value=""
                    checked={reassignAgentId === ""}
                    onChange={() => setReassignAgentId("")}
                    className="sr-only"
                  />
                  <span className="w-3 h-3 rounded-full border border-current shrink-0 flex items-center justify-center">
                    {reassignAgentId === "" && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
                  </span>
                  Don't reassign
                </label>
                {otherAgents.map((agent) => (
                  <label
                    key={agent.id}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer text-xs transition-colors ${
                      reassignAgentId === agent.id
                        ? "border-primary/50 bg-primary/5 text-foreground"
                        : "border-transparent text-muted-foreground hover:border-border/60"
                    }`}
                  >
                    <input
                      type="radio"
                      name="agent"
                      value={agent.id}
                      checked={reassignAgentId === agent.id}
                      onChange={() => setReassignAgentId(agent.id)}
                      className="sr-only"
                    />
                    <span className="w-3 h-3 rounded-full border border-current shrink-0 flex items-center justify-center">
                      {reassignAgentId === agent.id && (
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                      )}
                    </span>
                    {agent.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          {reassignAgentId && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-blue-500/5 border border-blue-500/20">
              <AlertTriangle className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
              <p className="text-[11px] text-blue-400 leading-relaxed">
                The task will be reassigned and queued for the new agent to pick up.
              </p>
            </div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => handleConfirm(!!reassignAgentId)}
              disabled={loading}
              className="bg-orange-500 text-white hover:bg-orange-600 gap-1.5"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : reassignAgentId ? (
                <RefreshCw className="w-3.5 h-3.5" />
              ) : (
                <StopCircle className="w-3.5 h-3.5" />
              )}
              {reassignAgentId ? "Interrupt & reassign" : "Interrupt"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
