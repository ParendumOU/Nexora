"use client";
import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { providersApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { Loader2, ChevronDown } from "lucide-react";
import { PROVIDER_MODELS } from "@/lib/provider-models";
import { ProviderDef, ProviderItem, PROVIDERS, providerDef } from "./provider-definitions";

function EditProviderDialog({ provider, onClose }: { provider: ProviderItem | null; onClose: () => void }) {
  const qc = useQueryClient();
  const def: ProviderDef = provider ? providerDef(provider.provider_type) : PROVIDERS[0];
  const models = provider?.available_models ?? PROVIDER_MODELS[provider?.provider_type ?? ""] ?? [];

  const [name, setName] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelIsCustom, setModelIsCustom] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [cooldown, setCooldown] = useState(60);
  const [loading, setLoading] = useState(false);

  // Sync state when provider changes
  useEffect(() => {
    if (!provider) return;
    setName(provider.name);
    const m = provider.model_name ?? "";
    setModelName(m);
    setModelIsCustom(m !== "" && models.length > 0 && !models.includes(m));
    setBaseUrl(provider.base_url ?? "");
    setApiKey("");
    setCooldown(provider.cooldown_seconds ?? 60);
  }, [provider?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = async () => {
    if (!provider) return;
    if (!name.trim()) { toast.error("Name is required"); return; }
    setLoading(true);
    try {
      const body: Record<string, unknown> = {
        name: name.trim(),
        model_name: modelName || null,
        cooldown_seconds: cooldown,
      };
      if (def.needsBaseUrl) body.base_url = baseUrl || null;
      if (apiKey.trim()) body.credentials = { api_key: apiKey.trim() };
      await providersApi.update(provider.id, body);
      qc.invalidateQueries({ queryKey: ["providers"] });
      toast.success("Account updated");
      onClose();
    } catch {
      toast.error("Failed to update account");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={!!provider} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-sm animate-fade-in">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", def.dot)} />
              Edit {def.label} Account
            </Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">{provider?.name}</p>
          </div>

          <div className="p-5 space-y-3">
            {/* Name */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Account name</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-sm" autoFocus />
            </div>

            {/* Model */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Model <span className="text-muted-foreground/50">(optional)</span>
              </label>
              {models.length > 0 && !modelIsCustom ? (
                <Select.Root
                  value={modelName || "__default__"}
                  onValueChange={(v) => {
                    if (v === "__custom__") { setModelIsCustom(true); setModelName(""); }
                    else if (v === "__default__") setModelName("");
                    else setModelName(v);
                  }}
                >
                  <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">
                    <Select.Value />
                    <ChevronDown className="w-3.5 h-3.5 opacity-50 shrink-0" />
                  </Select.Trigger>
                  <Select.Content position="popper" sideOffset={4}
                    className="z-[200] w-[var(--radix-select-trigger-width)] max-h-60 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1"
                  >
                    <Select.Item value="__default__" className="flex items-center px-3 py-1.5 text-xs rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent text-muted-foreground">
                      <Select.ItemText>Provider default</Select.ItemText>
                    </Select.Item>
                    {models.map((m) => (
                      <Select.Item key={m} value={m} className="flex items-center justify-between px-3 py-1.5 text-xs rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent font-mono">
                        <Select.ItemText>{m}</Select.ItemText>
                      </Select.Item>
                    ))}
                    <Select.Item value="__custom__" className="flex items-center px-3 py-1.5 text-xs rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent text-muted-foreground">
                      <Select.ItemText>Custom…</Select.ItemText>
                    </Select.Item>
                  </Select.Content>
                </Select.Root>
              ) : (
                <div className="flex gap-1.5 items-center">
                  {modelIsCustom && (
                    <button type="button" onClick={() => { setModelIsCustom(false); setModelName(""); }}
                      className="shrink-0 text-xs text-muted-foreground hover:text-foreground px-1.5 py-1 rounded border border-border hover:bg-accent transition-colors">
                      ←
                    </button>
                  )}
                  <Input placeholder={def.defaultModel ?? "model-name"} value={modelName}
                    onChange={(e) => setModelName(e.target.value)} className="h-8 text-sm" />
                </div>
              )}
            </div>

            {/* Base URL */}
            {def.needsBaseUrl && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {provider?.provider_type === "azure" ? "Azure endpoint" : provider?.provider_type === "ollama" ? "Ollama URL" : "Base URL"}
                </label>
                <Input placeholder={baseUrl || "https://..."} value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)} className="h-8 text-sm" />
              </div>
            )}

            {/* API key re-entry */}
            {provider?.auth_type === "apikey" && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {def.apiKeyLabel ?? "API Key"} <span className="text-muted-foreground/50">(leave blank to keep existing)</span>
                </label>
                <Input type="password" placeholder="••••••••" value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)} className="h-8 text-sm" />
              </div>
            )}

            {/* Cooldown */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Rate-limit cooldown (seconds)</label>
              <Input type="number" min={10} max={3600} value={cooldown}
                onChange={(e) => setCooldown(Number(e.target.value))} className="h-8 text-sm" />
            </div>

            <div className="flex gap-2 justify-end pt-1">
              <Button variant="outline" size="sm" onClick={onClose} disabled={loading}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={loading}>
                {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Saving…</> : "Save changes"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default EditProviderDialog;
