"use client";
import { useState, useEffect, useMemo } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { providersApi, providerTypesApi, ProviderTypeDef } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { Loader2, Plus, Trash2, ArrowDown, ChevronDown, Users, AlertTriangle } from "lucide-react";
import { ProviderItem, providerDef } from "./provider-definitions";

interface ChainStepLocal {
  providerType: string;
  modelName: string;
}

export interface ChainData {
  id: string;
  name: string;
  is_default: boolean;
  steps: Array<{ position: number; model_name: string | null; provider_type: string; account_count: number }>;
}

function ModelCombobox({ value, onChange, models, placeholder = "Provider default" }: {
  value: string;
  onChange: (v: string) => void;
  models: string[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const filtered = models.filter(m => !filter || m.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="relative w-40 shrink-0">
      <div className="flex items-center h-7 rounded border border-input bg-transparent px-2 gap-1">
        <input
          className="flex-1 text-xs bg-transparent outline-none min-w-0 font-mono placeholder:font-sans placeholder:text-muted-foreground"
          placeholder={placeholder}
          value={open ? filter : value}
          onChange={e => setFilter(e.target.value)}
          onFocus={() => { setOpen(true); setFilter(value); }}
          onBlur={() => setTimeout(() => {
            setOpen(false);
            if (filter && filter !== value) onChange(filter);
            setFilter("");
          }, 50)}
        />
        <ChevronDown className="w-3 h-3 opacity-50 shrink-0 pointer-events-none" />
      </div>
      {open && (
        <div className="absolute top-full left-0 z-[200] mt-1 w-56 max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
          <div
            className="flex items-center px-2 py-1.5 text-xs rounded cursor-pointer hover:bg-accent text-muted-foreground"
            onMouseDown={e => { e.preventDefault(); onChange(""); setOpen(false); setFilter(""); }}
          >
            Provider default
          </div>
          {filtered.map(m => (
            <div
              key={m}
              className={cn("flex items-center px-2 py-1.5 text-xs rounded cursor-pointer hover:bg-accent font-mono", m === value && "bg-accent/50")}
              onMouseDown={e => { e.preventDefault(); onChange(m); setOpen(false); setFilter(""); }}
            >
              {m}
            </div>
          ))}
          {filter && !models.some(m => m.toLowerCase() === filter.toLowerCase()) && (
            <div
              className="flex items-center gap-1 px-2 py-1.5 text-xs rounded cursor-pointer hover:bg-accent text-muted-foreground italic"
              onMouseDown={e => { e.preventDefault(); onChange(filter); setOpen(false); setFilter(""); }}
            >
              Use "{filter}"
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChainBuilderDialog({ open, onClose, providers, editChain }: {
  open: boolean;
  onClose: () => void;
  providers: ProviderItem[];
  editChain?: ChainData;
}) {
  const qc = useQueryClient();
  const [chainName, setChainName] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [steps, setSteps] = useState<ChainStepLocal[]>([]);
  const [loading, setLoading] = useState(false);

  // Seed-defined provider type definitions (for model lists)
  const { data: providerTypes = [] } = useQuery<ProviderTypeDef[]>({
    queryKey: ["provider-types"],
    queryFn: () => providerTypesApi.list().then(r => r.data),
  });

  // Unique provider types that have at least one account in this org
  const availableTypes = useMemo(() => {
    const seen = new Set<string>();
    providers.forEach(p => seen.add(p.provider_type));
    return Array.from(seen).sort();
  }, [providers]);

  // Count accounts per type in this org
  const accountCounts = useMemo(() => {
    const m: Record<string, number> = {};
    providers.forEach(p => { m[p.provider_type] = (m[p.provider_type] ?? 0) + 1; });
    return m;
  }, [providers]);

  // Models for a given provider_type from seed definitions
  const modelsFor = (pt: string): string[] =>
    providerTypes.find(t => t.key === pt)?.models ?? [];

  useEffect(() => {
    if (!open) return;
    if (editChain) {
      setChainName(editChain.name);
      setIsDefault(editChain.is_default);
      setSteps(editChain.steps.map(s => ({ providerType: s.provider_type, modelName: s.model_name ?? "" })));
    } else {
      setChainName("");
      setSteps([]);
      setIsDefault(false);
    }
  }, [open, editChain]);

  const addStep = () => {
    const firstType = availableTypes[0] ?? "";
    setSteps(s => [...s, { providerType: firstType, modelName: "" }]);
  };

  const removeStep = (idx: number) => setSteps(s => s.filter((_, i) => i !== idx));

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    setSteps(s => { const a = [...s]; [a[idx - 1], a[idx]] = [a[idx], a[idx - 1]]; return a; });
  };

  const updateStep = (idx: number, field: keyof ChainStepLocal, value: string) =>
    setSteps(s => s.map((step, i) => i === idx ? { ...step, [field]: value } : step));

  const handleSave = async () => {
    if (!chainName.trim()) { toast.error("Chain name required"); return; }
    if (!steps.length) { toast.error("Add at least one step"); return; }
    setLoading(true);
    try {
      const payload = steps.map(s => ({ provider_type: s.providerType, model_name: s.modelName || null }));
      if (editChain) {
        await providersApi.updateChain(editChain.id, { name: chainName, steps: payload, is_default: isDefault });
        toast.success("Chain updated");
      } else {
        await providersApi.createChain({ name: chainName, steps: payload, is_default: isDefault });
        toast.success("Chain created");
      }
      qc.invalidateQueries({ queryKey: ["chains"] });
      onClose();
      setChainName(""); setSteps([]); setIsDefault(false);
    } catch { toast.error(editChain ? "Failed to update chain" : "Failed to create chain"); }
    finally { setLoading(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-sm animate-fade-in overflow-hidden">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">
              {editChain ? "Edit Fallback Chain" : "Create Fallback Chain"}
            </Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">
              Each step specifies a provider type and optional model. All accounts of that type are tried in order on rate-limit.
            </p>
          </div>

          <div className="p-5 space-y-4 max-h-[65vh] overflow-y-auto">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Chain name</label>
              <Input
                placeholder="Primary, Production, Fallback…"
                value={chainName}
                onChange={e => setChainName(e.target.value)}
                className="h-8 text-sm"
                autoFocus
              />
            </div>

            {steps.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Steps — top is tried first</p>
                {steps.map((step, idx) => {
                  const def = providerDef(step.providerType);
                  const models = modelsFor(step.providerType);
                  const count = accountCounts[step.providerType] ?? 0;
                  return (
                    <div key={idx} className={cn("flex flex-col gap-2 px-3 py-2.5 bg-accent/20 border rounded-lg", count === 0 ? "border-amber-500/50" : "border-border")}>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground w-4 text-center shrink-0">{idx + 1}</span>

                        {/* Provider type select */}
                        <Select.Root
                          value={step.providerType}
                          onValueChange={v => updateStep(idx, "providerType", v)}
                        >
                          <Select.Trigger className="flex items-center gap-1.5 h-7 min-w-0 flex-1 rounded border border-input bg-transparent px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring">
                            <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", def.dot)} />
                            <Select.Value />
                            <ChevronDown className="w-3 h-3 opacity-50 shrink-0 ml-auto" />
                          </Select.Trigger>
                          <Select.Content position="popper" sideOffset={4}
                            className="z-[200] w-56 max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
                            {availableTypes.map(pt => {
                              const d = providerDef(pt);
                              return (
                                <Select.Item key={pt} value={pt}
                                  className="flex items-center gap-2 px-2 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                                  <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", d.dot)} />
                                  <Select.ItemText>{pt}</Select.ItemText>
                                  <span className={cn("ml-auto text-[10px]", d.color)}>{d.label}</span>
                                </Select.Item>
                              );
                            })}
                          </Select.Content>
                        </Select.Root>

                        {/* Model combobox — type to filter or enter custom model */}
                        <ModelCombobox
                          value={step.modelName}
                          onChange={v => updateStep(idx, "modelName", v)}
                          models={models}
                        />

                        <button onClick={() => moveUp(idx)} disabled={idx === 0}
                          className="p-1 rounded hover:bg-accent disabled:opacity-30 shrink-0">
                          <ArrowDown className="w-3 h-3 rotate-180" />
                        </button>
                        <button onClick={() => removeStep(idx)}
                          className="p-1 rounded hover:text-destructive shrink-0">
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>

                      {/* Account count hint */}
                      {step.providerType && (
                        <p className={cn("flex items-center gap-1 text-[10px] pl-6", count === 0 ? "text-amber-500" : "text-muted-foreground")}>
                          {count === 0
                            ? <AlertTriangle className="w-2.5 h-2.5 shrink-0" />
                            : <Users className="w-2.5 h-2.5 shrink-0" />}
                          {count} account{count !== 1 ? "s" : ""} —
                          {count > 1 ? " rotates on rate-limit" : count === 1 ? " add more for auto-failover" : " no active accounts, step will fail"}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <button
              onClick={addStep}
              disabled={availableTypes.length === 0}
              className="flex items-center gap-2 w-full px-3 py-2 border border-dashed border-border rounded-lg hover:border-primary/40 hover:bg-accent/20 transition-colors text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              <Plus className="w-3 h-3" /> Add step
            </button>

            {availableTypes.length === 0 && (
              <p className="text-xs text-muted-foreground text-center">Add accounts first.</p>
            )}

            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} className="rounded border-border" />
              <span className="text-sm">Set as default for new chats</span>
            </label>
          </div>

          <div className="flex gap-2 justify-end px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" onClick={onClose} disabled={loading}>Cancel</Button>
            <Button size="sm" onClick={handleSave} disabled={loading}>
              {loading
                ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />{editChain ? "Saving…" : "Creating…"}</>
                : editChain ? "Save Changes" : "Create Chain"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default ChainBuilderDialog;
