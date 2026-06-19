"use client";
import { useState, useEffect, useMemo } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { X, Plus, Users } from "lucide-react";
import toast from "react-hot-toast";
import { modelProfilesApi, providerTypesApi, ProviderTypeDef } from "@/lib/api";

export interface ModelProfileData {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  provider_chain_id: string | null;
  provider_type: string | null;
  model_name: string | null;
  is_active: boolean;
  created_at: string;
  chain_name: string | null;
  account_count: number;
  priority: number;
}

interface Chain {
  id: string;
  name: string;
  steps?: Array<unknown>;
}

interface ProviderAccount {
  id: string;
  name: string;
  provider_type: string;
  available_models: string[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  editProfile?: ModelProfileData;
  chains: Chain[];
  providers: ProviderAccount[];
}

const SUGGESTED_TAGS = ["coding", "cheap", "fast", "smart", "creative", "analysis", "general", "expensive", "vision", "reasoning"];

export default function ModelProfileDialog({ open, onClose, editProfile, chains, providers }: Props) {
  const qc = useQueryClient();
  const isEdit = !!editProfile;

  const [name, setName] = useState("");
  const [priority, setPriority] = useState(0);
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [routeMode, setRouteMode] = useState<"provider_type" | "chain">("provider_type");
  const [selectedProviderType, setSelectedProviderType] = useState("");
  const [selectedChainId, setSelectedChainId] = useState("");
  const [modelName, setModelName] = useState("");
  const [isActive, setIsActive] = useState(true);

  // Unique provider types present in this org's accounts
  const availableProviderTypes = useMemo(() => {
    const seen = new Set<string>();
    return providers.filter(p => { const n = !seen.has(p.provider_type); seen.add(p.provider_type); return n; })
      .map(p => p.provider_type)
      .sort();
  }, [providers]);

  // Count how many accounts exist for the selected provider_type
  const accountCount = useMemo(
    () => providers.filter(p => p.provider_type === selectedProviderType).length,
    [providers, selectedProviderType]
  );

  // Models list for selected provider_type — from seed definitions
  // We'll receive this as a prop derived from providerTypesApi in the parent,
  // but since it's cheap to hold locally we just look up from providers' available_models
  const availableModels = useMemo(() => {
    const models = new Set<string>();
    providers
      .filter(p => p.provider_type === selectedProviderType)
      .forEach(p => (p.available_models ?? []).forEach(m => models.add(m)));
    return Array.from(models).sort();
  }, [providers, selectedProviderType]);

  useEffect(() => {
    if (!open) return;
    if (editProfile) {
      setName(editProfile.name);
      setDescription(editProfile.description || "");
      setTags(editProfile.tags);
      const chainIsSolo = editProfile.provider_chain_id
        ? (chains.find(c => c.id === editProfile.provider_chain_id)?.steps?.length ?? 2) <= 1
        : false;
      setRouteMode(editProfile.provider_chain_id && !chainIsSolo ? "chain" : "provider_type");
      setSelectedProviderType(editProfile.provider_type || "");
      setSelectedChainId(editProfile.provider_chain_id || "");
      setModelName(editProfile.model_name || "");
      setIsActive(editProfile.is_active);
      setPriority(editProfile.priority ?? 0);
    } else {
      setName("");
      setDescription("");
      setTags([]);
      setTagInput("");
      setRouteMode("provider_type");
      setSelectedProviderType(availableProviderTypes[0] || "");
      setSelectedChainId("");
      setModelName("");
      setIsActive(true);
      setPriority(0);
    }
  }, [editProfile, open]);

  const save = useMutation({
    mutationFn: (data: Parameters<typeof modelProfilesApi.create>[0]) =>
      isEdit
        ? modelProfilesApi.update(editProfile!.id, data)
        : modelProfilesApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["model-profiles"] });
      toast.success(isEdit ? "Profile updated" : "Profile created");
      onClose();
    },
    onError: () => toast.error("Failed to save profile"),
  });

  const addTag = (tag: string) => {
    const t = tag.trim().toLowerCase();
    if (t && !tags.includes(t)) setTags(prev => [...prev, t]);
    setTagInput("");
  };
  const removeTag = (tag: string) => setTags(prev => prev.filter(t => t !== tag));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    save.mutate({
      name: name.trim(),
      description: description.trim() || undefined,
      tags,
      provider_type: routeMode === "provider_type" ? (selectedProviderType || null) : null,
      provider_chain_id: routeMode === "chain" ? (selectedChainId || null) : null,
      model_name: modelName.trim() || null,
      is_active: isActive,
      priority,
    });
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-background border border-border rounded-lg w-full max-w-lg shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold">{isEdit ? "Edit Model Profile" : "New Model Profile"}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium mb-1">Name *</label>
            <input
              className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="e.g. Budget Worker, Code Expert"
              value={name}
              onChange={e => setName(e.target.value)}
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium mb-1">Description</label>
            <input
              className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="When should agents use this profile?"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-medium mb-1">Tags</label>
            <div className="flex flex-wrap gap-1 mb-2">
              {tags.map(tag => (
                <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-primary/10 text-primary rounded-full">
                  {tag}
                  <button type="button" onClick={() => removeTag(tag)} className="hover:text-destructive">
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                className="flex-1 px-3 py-1.5 text-xs bg-muted border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="Add tag and press Enter"
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") { e.preventDefault(); addTag(tagInput); }
                  if (e.key === ",") { e.preventDefault(); addTag(tagInput); }
                }}
              />
              <button type="button" onClick={() => addTag(tagInput)}
                className="px-2 py-1.5 text-xs bg-muted border border-border rounded hover:bg-accent">
                <Plus size={12} />
              </button>
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {SUGGESTED_TAGS.filter(t => !tags.includes(t)).map(t => (
                <button key={t} type="button" onClick={() => addTag(t)}
                  className="px-2 py-0.5 text-xs text-muted-foreground border border-border rounded-full hover:bg-accent hover:text-foreground">
                  + {t}
                </button>
              ))}
            </div>
          </div>

          {/* Route mode */}
          <div>
            <label className="block text-xs font-medium mb-2">Route to</label>
            <div className="flex gap-2 mb-3">
              {(["provider_type", "chain"] as const).map(m => (
                <button key={m} type="button" onClick={() => setRouteMode(m)}
                  className={`px-3 py-1.5 text-xs rounded border transition-colors ${
                    routeMode === m
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-muted border-border text-muted-foreground hover:text-foreground"
                  }`}>
                  {m === "provider_type" ? "Provider + Model" : "Fallback Chain"}
                </button>
              ))}
            </div>

            {routeMode === "provider_type" ? (
              <div className="space-y-2">
                {/* Provider type picker */}
                <select
                  className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none"
                  value={selectedProviderType}
                  onChange={e => { setSelectedProviderType(e.target.value); setModelName(""); }}
                >
                  <option value="">— select provider —</option>
                  {availableProviderTypes.map(pt => (
                    <option key={pt} value={pt}>{pt}</option>
                  ))}
                </select>

                {/* Model picker */}
                {selectedProviderType && (
                  availableModels.length > 0 ? (
                    <select
                      className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none"
                      value={modelName}
                      onChange={e => setModelName(e.target.value)}
                    >
                      <option value="">— any model (provider default) —</option>
                      {availableModels.map(m => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none"
                      placeholder="Model name (leave blank for provider default)"
                      value={modelName}
                      onChange={e => setModelName(e.target.value)}
                    />
                  )
                )}

                {/* Account count hint */}
                {selectedProviderType && (
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Users size={11} />
                    {accountCount} account{accountCount !== 1 ? "s" : ""} linked —
                    {accountCount > 1
                      ? " agent will rotate automatically on rate-limit"
                      : accountCount === 1
                      ? " add more accounts of this type for automatic failover"
                      : " no accounts found for this provider type"}
                  </p>
                )}
              </div>
            ) : (
              <select
                className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none"
                value={selectedChainId}
                onChange={e => setSelectedChainId(e.target.value)}
              >
                <option value="">— no chain —</option>
                {chains
                  .filter(c => !c.steps || c.steps.length > 1)
                  .map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
              </select>
            )}
          </div>

          {/* Priority */}
          <div>
              <label className="text-xs font-medium text-muted-foreground">Priority</label>
              <input
                type="number"
                min={0}
                max={999}
                value={priority}
                onChange={e => setPriority(Number(e.target.value))}
                className="mt-1 w-full px-3 py-1.5 text-sm border border-border rounded bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <p className="text-[10px] text-muted-foreground mt-0.5">Higher = tried first when routing.</p>
            </div>

          {/* Active toggle */}
          <div className="flex items-center gap-2">
            <input type="checkbox" id="is_active" checked={isActive}
              onChange={e => setIsActive(e.target.checked)} className="w-4 h-4" />
            <label htmlFor="is_active" className="text-xs">Active</label>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-xs bg-muted border border-border rounded hover:bg-accent">
              Cancel
            </button>
            <button type="submit" disabled={save.isPending || !name.trim()}
              className="px-4 py-2 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50">
              {save.isPending ? "Saving…" : isEdit ? "Save Changes" : "Create Profile"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
