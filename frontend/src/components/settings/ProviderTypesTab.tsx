"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Lock, Globe, Cpu, ExternalLink, ChevronDown, ChevronRight, X, Download, Upload, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import { providerTypesApi, ProviderTypeDef } from "@/lib/api";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";

// ── Stream type colors ────────────────────────────────────────────────────────
const STREAM_COLORS: Record<string, string> = {
  claude:        "bg-orange-400/15 text-orange-400 border-orange-400/20",
  gemini:        "bg-blue-400/15 text-blue-400 border-blue-400/20",
  ollama:        "bg-purple-400/15 text-purple-400 border-purple-400/20",
  openai_compat: "bg-green-400/15 text-green-400 border-green-400/20",
};

const AUTH_COLORS: Record<string, string> = {
  oauth:  "bg-amber-400/15 text-amber-400 border-amber-400/20",
  apikey: "bg-sky-400/15 text-sky-400 border-sky-400/20",
  none:   "bg-muted text-muted-foreground border-border",
};

function Chip({ label, className }: { label: string; className?: string }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded border ${className}`}>
      {label}
    </span>
  );
}

function ProviderDot({ streamType }: { streamType: string }) {
  const colors: Record<string, string> = {
    claude: "bg-orange-400", gemini: "bg-blue-400",
    ollama: "bg-purple-400", openai_compat: "bg-green-400",
  };
  return <span className={`w-2 h-2 rounded-full shrink-0 ${colors[streamType] ?? "bg-muted-foreground"}`} />;
}

// ── Provider Type Form Dialog ─────────────────────────────────────────────────

interface FormState {
  key: string; name: string; description: string;
  category: "oauth" | "api"; auth_type: "oauth" | "apikey" | "none";
  stream_type: "claude" | "gemini" | "ollama" | "openai_compat";
  base_url: string; requires_base_url: boolean;
  default_model: string; models: string; website: string;
  cli_command: string; cli_login_args: string; credential_paths: string;
  credential_format: "claude_oauth" | "raw_json" | "token_pair";
}

const EMPTY_FORM: FormState = {
  key: "", name: "", description: "", category: "api",
  auth_type: "apikey", stream_type: "openai_compat",
  base_url: "", requires_base_url: false,
  default_model: "", models: "", website: "",
  cli_command: "", cli_login_args: "", credential_paths: "",
  credential_format: "raw_json",
};

function defToForm(d: ProviderTypeDef): FormState {
  return {
    key: d.key, name: d.name, description: d.description,
    category: d.category, auth_type: d.auth_type, stream_type: d.stream_type,
    base_url: d.base_url ?? "", requires_base_url: d.requires_base_url,
    default_model: d.default_model ?? "", models: (d.models ?? []).join("\n"),
    website: d.website ?? "",
    cli_command: d.cli_command ?? "",
    cli_login_args: (d.cli_login_args ?? []).join(" "),
    credential_paths: (d.credential_paths ?? []).join("\n"),
    credential_format: (d.credential_format as FormState["credential_format"]) ?? "raw_json",
  };
}

function formToPayload(f: FormState) {
  return {
    key: f.key.trim().toLowerCase(),
    name: f.name.trim(),
    description: f.description.trim(),
    category: f.category,
    auth_type: f.auth_type,
    stream_type: f.stream_type,
    base_url: f.base_url.trim() || null,
    requires_base_url: f.requires_base_url,
    default_model: f.default_model.trim() || null,
    models: f.models.split(/[\n,]+/).map(s => s.trim()).filter(Boolean),
    website: f.website.trim() || null,
    cli_command: f.cli_command.trim() || null,
    cli_login_args: f.cli_login_args.trim() ? f.cli_login_args.trim().split(/\s+/) : [],
    credential_paths: f.credential_paths.split("\n").map(s => s.trim()).filter(Boolean),
    credential_format: f.credential_format,
  };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-foreground">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Input({ value, onChange, placeholder, disabled, className = "" }: {
  value: string; onChange: (v: string) => void;
  placeholder?: string; disabled?: boolean; className?: string;
}) {
  return (
    <input
      className={`w-full px-2.5 py-1.5 text-xs bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 ${className}`}
      value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder} disabled={disabled}
    />
  );
}

function Textarea({ value, onChange, placeholder, rows = 3 }: {
  value: string; onChange: (v: string) => void; placeholder?: string; rows?: number;
}) {
  return (
    <textarea
      rows={rows}
      className="w-full px-2.5 py-1.5 text-xs bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary resize-none font-mono"
      value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
    />
  );
}

function Select({ value, onChange, options }: {
  value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      className="w-full px-2.5 py-1.5 text-xs bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
      value={value} onChange={e => onChange(e.target.value)}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function ProviderTypeDialog({
  open, editing, onClose,
}: {
  open: boolean;
  editing: ProviderTypeDef | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(editing ? defToForm(editing) : EMPTY_FORM);
  const [fetchingModels, setFetchingModels] = useState(false);
  const isEditing = !!editing;

  const set = (k: keyof FormState) => (v: string | boolean) =>
    setForm(prev => ({ ...prev, [k]: v }));

  const createMut = useMutation({
    mutationFn: (data: object) => providerTypesApi.create(data as any),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-types"] });
      toast.success("Provider type created");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Failed to create"),
  });

  const updateMut = useMutation({
    mutationFn: (data: object) => providerTypesApi.update(editing!.key, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-types"] });
      toast.success("Provider type updated");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Failed to update"),
  });

  if (!open) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload = formToPayload(form);
    if (!payload.name) { toast.error("Name is required"); return; }
    if (!isEditing && !payload.key) { toast.error("Key is required"); return; }
    isEditing ? updateMut.mutate(payload) : createMut.mutate(payload);
  };

  const busy = createMut.isPending || updateMut.isPending;

  const handleFetchModels = async () => {
    if (!form.base_url.trim()) { toast.error("Base URL is required to fetch models"); return; }
    setFetchingModels(true);
    try {
      const res = await providerTypesApi.fetchModels({
        base_url: form.base_url.trim(),
        api_key: null,
        stream_type: form.stream_type,
      });
      const models = res.data.models;
      if (models.length === 0) { toast.error("No models returned by provider"); return; }
      setForm(prev => ({ ...prev, models: models.join("\n") }));
      toast.success(`Fetched ${models.length} model${models.length !== 1 ? "s" : ""}`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Failed to fetch models");
    } finally {
      setFetchingModels(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-2xl max-h-[90vh] flex flex-col shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div>
            <h2 className="text-sm font-semibold">{isEditing ? `Edit — ${editing!.name}` : "New Provider Type"}</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {isEditing ? "Modifies the seed JSON file on disk" : "Creates a custom seed file in seeds/providers/{category}/custom/"}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* Basic */}
          <section className="space-y-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Basic Info</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Key *" hint="Slug used internally (e.g. my-provider). Cannot be changed after creation.">
                <Input value={form.key} onChange={set("key")} placeholder="my-provider"
                  disabled={isEditing} className={isEditing ? "opacity-50 cursor-not-allowed" : ""} />
              </Field>
              <Field label="Name *">
                <Input value={form.name} onChange={set("name")} placeholder="My Provider" />
              </Field>
            </div>
            <Field label="Description">
              <Input value={form.description} onChange={set("description")} placeholder="Brief description shown in the UI" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Website">
                <Input value={form.website} onChange={set("website")} placeholder="https://example.com" />
              </Field>
              <Field label="Category">
                <Select value={form.category} onChange={set("category") as any} options={[
                  { value: "api", label: "API — key-authenticated or local" },
                  { value: "oauth", label: "OAuth — CLI browser-based auth" },
                ]} />
              </Field>
            </div>
          </section>

          {/* Integration */}
          <section className="space-y-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Integration</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Auth Type">
                <Select value={form.auth_type} onChange={set("auth_type") as any} options={[
                  { value: "apikey", label: "API Key" },
                  { value: "oauth",  label: "OAuth (CLI)" },
                  { value: "none",   label: "None (local)" },
                ]} />
              </Field>
              <Field label="Stream Type" hint="Determines which streaming backend is used.">
                <Select value={form.stream_type} onChange={set("stream_type") as any} options={[
                  { value: "openai_compat", label: "OpenAI-compatible" },
                  { value: "claude",        label: "Claude (Anthropic SDK)" },
                  { value: "gemini",        label: "Gemini (Google SDK)" },
                  { value: "ollama",        label: "Ollama (local REST)" },
                ]} />
              </Field>
            </div>
          </section>

          {/* API Config */}
          <section className="space-y-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">API Config</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Base URL" hint="Leave blank if each instance provides its own.">
                <Input value={form.base_url} onChange={set("base_url")} placeholder="https://api.example.com/v1" />
              </Field>
              <Field label="Default Model">
                <Input value={form.default_model} onChange={set("default_model")} placeholder="model-name-here" />
              </Field>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" id="requires_base_url" checked={form.requires_base_url}
                onChange={e => set("requires_base_url")(e.target.checked)}
                className="w-3.5 h-3.5 accent-primary" />
              <label htmlFor="requires_base_url" className="text-xs text-foreground cursor-pointer">
                Requires base URL (user must provide one — e.g. Azure)
              </label>
            </div>
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-foreground">Available Models</label>
                <button
                  type="button"
                  onClick={handleFetchModels}
                  disabled={fetchingModels || !form.base_url.trim()}
                  className="flex items-center gap-1 px-2 py-0.5 text-[10px] rounded border border-border hover:bg-muted disabled:opacity-40 transition-colors"
                >
                  <RefreshCw size={9} className={fetchingModels ? "animate-spin" : ""} />
                  {fetchingModels ? "Fetching…" : "Fetch from API"}
                </button>
              </div>
              <Textarea value={form.models} onChange={set("models")}
                placeholder={"model-large\nmodel-small"} rows={3} />
              <p className="text-[10px] text-muted-foreground">One per line or comma-separated. Used as fallback list in the UI.</p>
            </div>
          </section>

          {/* OAuth Config — shown when auth_type is oauth */}
          {form.auth_type === "oauth" && (
            <section className="space-y-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">OAuth / CLI Config</h3>
              <div className="grid grid-cols-2 gap-3">
                <Field label="CLI Command" hint="Binary name (e.g. claude, gemini, codex).">
                  <Input value={form.cli_command} onChange={set("cli_command")} placeholder="my-cli" />
                </Field>
                <Field label="Login Args" hint="Space-separated CLI arguments for the login command.">
                  <Input value={form.cli_login_args} onChange={set("cli_login_args")} placeholder="auth login --browser" />
                </Field>
              </div>
              <Field label="Credential Paths" hint="Relative paths from HOME dir, one per line. First match wins.">
                <Textarea value={form.credential_paths} onChange={set("credential_paths")}
                  placeholder={".my-provider/auth.json"} rows={3} />
              </Field>
              <Field label="Credential Format" hint="Controls how the credential file is parsed.">
                <Select value={form.credential_format} onChange={set("credential_format") as any} options={[
                  { value: "raw_json",     label: "Raw JSON (direct read)" },
                  { value: "token_pair",   label: "Token Pair (access_token / refresh_token)" },
                  { value: "claude_oauth", label: "Claude OAuth (nested claudeAiOauth structure)" },
                ]} />
              </Field>
            </section>
          )}
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-border shrink-0">
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 text-xs rounded border border-border hover:bg-muted transition-colors">
            Cancel
          </button>
          <button type="submit" disabled={busy} onClick={handleSubmit}
            className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
            {busy ? "Saving…" : isEditing ? "Save Changes" : "Create Provider Type"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Provider Type Row ─────────────────────────────────────────────────────────

function ProviderTypeRow({
  def, onEdit, onDelete,
}: {
  def: ProviderTypeDef;
  onEdit: (d: ProviderTypeDef) => void;
  onDelete: (d: ProviderTypeDef) => void;
}) {
  const isBuiltin = def.source === "builtin";
  return (
    <div className="flex items-start gap-3 px-4 py-3 hover:bg-muted/30 transition-colors group">
      <div className="flex items-center gap-2 mt-0.5">
        <ProviderDot streamType={def.stream_type} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium font-mono">{def.key}</span>
          <span className="text-xs text-muted-foreground">{def.name}</span>
          {isBuiltin && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded border bg-muted text-muted-foreground border-border">
              <Lock size={9} /> Built-in
            </span>
          )}
          <Chip label={def.stream_type.replace("_", " ")} className={STREAM_COLORS[def.stream_type] ?? ""} />
          <Chip label={def.auth_type} className={AUTH_COLORS[def.auth_type] ?? ""} />
        </div>
        {def.description && (
          <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{def.description}</p>
        )}
        <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
          {def.base_url && (
            <span className="flex items-center gap-1"><Globe size={9} />{def.base_url}</span>
          )}
          {def.default_model && (
            <span className="flex items-center gap-1"><Cpu size={9} />{def.default_model}</span>
          )}
          {(def.models?.length ?? 0) > 0 && (
            <span>{def.models.length} model{def.models.length !== 1 ? "s" : ""}</span>
          )}
          {def.website && (
            <a href={def.website} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-foreground transition-colors">
              <ExternalLink size={9} /> Docs
            </a>
          )}
        </div>
      </div>
      {!isBuiltin && (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={() => onEdit(def)}
            className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
            <Pencil size={12} />
          </button>
          <button onClick={() => onDelete(def)}
            className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors">
            <Trash2 size={12} />
          </button>
        </div>
      )}
    </div>
  );
}

// ── Category Section ──────────────────────────────────────────────────────────

function CategorySection({
  title, providers, onEdit, onDelete,
}: {
  title: string;
  providers: ProviderTypeDef[];
  onEdit: (d: ProviderTypeDef) => void;
  onDelete: (d: ProviderTypeDef) => void;
}) {
  const [open, setOpen] = useState(true);
  const builtin = providers.filter(p => p.source === "builtin");
  const custom   = providers.filter(p => p.source === "custom");

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-muted/40 hover:bg-muted/60 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold">{title}</span>
          <span className="text-[10px] text-muted-foreground">{providers.length} types</span>
          {custom.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded-full">
              {custom.length} custom
            </span>
          )}
        </div>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>

      {open && (
        <div className="divide-y divide-border">
          {builtin.length > 0 && (
            <>
              <div className="px-4 py-1.5 bg-muted/20">
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Built-in</span>
              </div>
              {builtin.map(p => (
                <ProviderTypeRow key={p.key} def={p} onEdit={onEdit} onDelete={onDelete} />
              ))}
            </>
          )}
          {custom.length > 0 && (
            <>
              <div className="px-4 py-1.5 bg-muted/20">
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Custom</span>
              </div>
              {custom.map(p => (
                <ProviderTypeRow key={p.key} def={p} onEdit={onEdit} onDelete={onDelete} />
              ))}
            </>
          )}
          {providers.length === 0 && (
            <p className="px-4 py-4 text-xs text-muted-foreground">No provider types in this category.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────────

export default function ProviderTypesTab() {
  const qc = useQueryClient();
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState<ProviderTypeDef | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ProviderTypeDef | null>(null);
  const [importing, setImporting] = useState(false);

  const { data: types = [], isLoading } = useQuery<ProviderTypeDef[]>({
    queryKey: ["provider-types"],
    queryFn: () => providerTypesApi.list().then(r => r.data),
  });

  const deleteMut = useMutation({
    mutationFn: (key: string) => providerTypesApi.delete(key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-types"] });
      toast.success("Provider type deleted");
      setPendingDelete(null);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Failed to delete"),
  });

  const oauthTypes = types.filter(t => t.category === "oauth");
  const apiTypes   = types.filter(t => t.category === "api");

  const openEdit = (d: ProviderTypeDef) => { setEditing(d); setShowDialog(true); };
  const openNew  = () => { setEditing(null); setShowDialog(true); };
  const closeDialog = () => { setShowDialog(false); setEditing(null); };

  const handleExport = async () => {
    const customCount = types.filter(t => t.source === "custom").length;
    if (customCount === 0) { toast.error("No custom provider types to export"); return; }
    try {
      const res = await providerTypesApi.export();
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/zip" }));
      const a = document.createElement("a");
      a.href = url; a.download = "custom_provider_types.zip"; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Export failed"); }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const res = await providerTypesApi.importZip(file);
      const { imported, skipped } = res.data;
      toast.success(`Imported ${imported.length} file(s)${skipped.length ? `, skipped ${skipped.length}` : ""}`);
      qc.invalidateQueries({ queryKey: ["provider-types"] });
    } catch { toast.error("Import failed — check the ZIP structure"); }
    finally { setImporting(false); e.target.value = ""; }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold">Provider Types</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Seed definitions for LLM providers. Built-in types are read-only; custom types are stored
            in <code className="font-mono text-[10px] bg-muted px-1 rounded">seeds/providers/&#123;category&#125;/custom/</code> and can be fully managed here.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border hover:bg-muted transition-colors"
          >
            <Download size={12} /> Export Custom
          </button>
          <label className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border hover:bg-muted transition-colors cursor-pointer ${importing ? "opacity-50 pointer-events-none" : ""}`}>
            <Upload size={12} /> {importing ? "Importing…" : "Import ZIP"}
            <input type="file" accept=".zip" className="hidden" onChange={handleImport} disabled={importing} />
          </label>
          <button
            onClick={openNew}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus size={13} /> New Provider Type
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground animate-pulse">Loading provider types…</div>
      ) : (
        <div className="space-y-4">
          <CategorySection
            title="OAuth Providers"
            providers={oauthTypes}
            onEdit={openEdit}
            onDelete={setPendingDelete}
          />
          <CategorySection
            title="API Providers"
            providers={apiTypes}
            onEdit={openEdit}
            onDelete={setPendingDelete}
          />
        </div>
      )}

      <ProviderTypeDialog open={showDialog} editing={editing} onClose={closeDialog} />

      <ConfirmDeleteDialog
        open={!!pendingDelete}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteMut.mutate(pendingDelete.key)}
        loading={deleteMut.isPending}
        title="Delete provider type?"
        description={`"${pendingDelete?.name}" (${pendingDelete?.key}) will be permanently removed from disk.`}
        destroys={[
          "The seed JSON file and its directory",
          "The provider type from the streaming registry (requires restart to take effect)",
        ]}
      />
    </div>
  );
}
