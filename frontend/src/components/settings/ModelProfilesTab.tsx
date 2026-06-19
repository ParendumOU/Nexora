"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Link2, Cpu, Tag, Users } from "lucide-react";
import toast from "react-hot-toast";
import { modelProfilesApi, providersApi } from "@/lib/api";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import ModelProfileDialog, { ModelProfileData } from "./ModelProfileDialog";

const PROVIDER_ICONS: Record<string, string> = {
  claude: "🟠", gemini: "🔵", openai: "🟢", ollama: "🦙",
  deepseek: "🔷", groq: "⚡", openrouter: "🔀", xai: "✗",
  mistral: "🌊", cohere: "🔶", "opencode-go": "🚀", "opencode-zen": "🧘",
  codex: "🤖", default: "🤖",
};

function TagChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-primary/10 text-primary rounded-full">
      <Tag size={9} />
      {label}
    </span>
  );
}

export default function ModelProfilesTab() {
  const qc = useQueryClient();
  const [showDialog, setShowDialog] = useState(false);
  const [editingProfile, setEditingProfile] = useState<ModelProfileData | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);

  const { data: profiles = [], isLoading } = useQuery<ModelProfileData[]>({
    queryKey: ["model-profiles"],
    queryFn: () => modelProfilesApi.list().then(r => r.data),
  });

  const { data: providers = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: () => providersApi.list().then(r => r.data),
  });

  const { data: chains = [] } = useQuery({
    queryKey: ["chains"],
    queryFn: () => providersApi.chains().then(r => r.data),
  });

  const deleteProfile = useMutation({
    mutationFn: (id: string) => modelProfilesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["model-profiles"] });
      toast.success("Profile deleted");
      setPendingDelete(null);
    },
    onError: () => toast.error("Failed to delete profile"),
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      modelProfilesApi.update(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-profiles"] }),
    onError: () => toast.error("Failed to update profile"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Model Profiles</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Define LLM routing by provider type and model. Agents pick the best profile by tags;
            if multiple accounts share the same type, failover is automatic.
          </p>
        </div>
        <button
          onClick={() => { setEditingProfile(null); setShowDialog(true); }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90"
        >
          <Plus size={12} />
          New Profile
        </button>
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground">Loading…</div>
      ) : profiles.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <Cpu size={24} className="mx-auto mb-2 text-muted-foreground/50" />
          <p className="text-sm font-medium">No model profiles yet</p>
          <p className="text-xs text-muted-foreground mt-1">
            Create profiles like "Cheap Worker" or "Code Expert" tagged with use-case labels.
            Agents will pick the right one when spawning sub-tasks.
          </p>
          <button
            onClick={() => { setEditingProfile(null); setShowDialog(true); }}
            className="mt-3 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90"
          >
            Create first profile
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {[...profiles].sort((a, b) => {
            if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
            if (b.priority !== a.priority) return b.priority - a.priority;
            return a.name.localeCompare(b.name);
          }).map(profile => {
            const icon = profile.provider_type
              ? (PROVIDER_ICONS[profile.provider_type] ?? PROVIDER_ICONS.default)
              : "🔗";
            return (
              <div
                key={profile.id}
                className={`border border-border rounded-lg p-4 transition-opacity ${!profile.is_active ? "opacity-50" : ""}`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{profile.name}</span>
                      {profile.priority > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded font-mono">p{profile.priority}</span>
                      )}
                      {!profile.is_active && (
                        <span className="text-xs px-1.5 py-0.5 bg-muted text-muted-foreground rounded">inactive</span>
                      )}
                    </div>
                    {profile.description && (
                      <p className="text-xs text-muted-foreground mt-0.5">{profile.description}</p>
                    )}

                    <div className="flex flex-wrap gap-1 mt-2">
                      {profile.tags.map(tag => <TagChip key={tag} label={tag} />)}
                    </div>

                    <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground flex-wrap">
                      {profile.provider_type ? (
                        <>
                          <span className="flex items-center gap-1">
                            <span>{icon}</span>
                            <span className="text-foreground font-medium">{profile.provider_type}</span>
                          </span>
                          {profile.model_name && (
                            <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{profile.model_name}</span>
                          )}
                          <span className="flex items-center gap-1">
                            <Users size={10} />
                            {profile.account_count} account{profile.account_count !== 1 ? "s" : ""}
                          </span>
                        </>
                      ) : profile.provider_chain_id ? (
                        <span className="flex items-center gap-1">
                          <Link2 size={11} />
                          Chain: <span className="text-foreground">{profile.chain_name || profile.provider_chain_id.slice(0, 8)}</span>
                        </span>
                      ) : (
                        <span className="text-destructive/70">No provider configured</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => toggleActive.mutate({ id: profile.id, is_active: !profile.is_active })}
                      className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded"
                    >
                      {profile.is_active ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => { setEditingProfile(profile); setShowDialog(true); }}
                      className="p-1.5 text-muted-foreground hover:text-foreground border border-border rounded"
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => setPendingDelete({ id: profile.id, name: profile.name })}
                      className="p-1.5 text-muted-foreground hover:text-destructive border border-border rounded"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ModelProfileDialog
        open={showDialog}
        onClose={() => { setShowDialog(false); setEditingProfile(null); }}
        editProfile={editingProfile ?? undefined}
        chains={chains as { id: string; name: string; steps: unknown[] }[]}
        providers={providers as { id: string; name: string; provider_type: string; available_models: string[] }[]}
      />

      <ConfirmDeleteDialog
        open={!!pendingDelete}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteProfile.mutate(pendingDelete.id)}
        loading={deleteProfile.isPending}
        title="Delete model profile?"
        description={`"${pendingDelete?.name}" will be permanently removed.`}
        destroys={["Profile configuration and tags", "Any tasks currently referencing this profile"]}
      />
    </div>
  );
}
