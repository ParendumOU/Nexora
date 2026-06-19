"use client";
import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { KeyRound, Loader2, Check, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { envVarsApi, orgsApi, type EnvVarResolveEntry } from "@/lib/api";
import toast from "react-hot-toast";

export interface RequiredEnvVar {
  key: string;
  tools: string[];
}

export interface EnvVarModalProps {
  open: boolean;
  onClose: () => void;
  /** required_env_vars from an import response. */
  required: RequiredEnvVar[];
  label?: string;
}

interface OrgLite { id: string; name: string }

/**
 * Install-time credentials modal (shown after the dependency modal). Lists the
 * env vars the imported tools need; for each, shows whether it's already
 * configured at org/user scope, and lets the user add a value for any that
 * aren't — stored as an org (shared) or personal variable, no server .env needed.
 *
 * Variables can share a KEY (e.g. prod + test STRIPE_SECRET_KEY); each gets a
 * unique `name`. At run time the value resolves org-first, then user.
 */
export function EnvVarModal({ open, onClose, required, label }: EnvVarModalProps) {
  const [configured, setConfigured] = useState<Record<string, EnvVarResolveEntry["configured"]>>({});
  const [orgs, setOrgs] = useState<OrgLite[]>([]);
  const [forms, setForms] = useState<Record<string, { open: boolean; scope: "user" | "org"; name: string; value: string; busy: boolean }>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || required.length === 0) return;
    setLoading(true);
    const keys = required.map((r) => r.key);
    Promise.all([
      envVarsApi.resolve(keys).then((r) => r.data.keys).catch(() => [] as EnvVarResolveEntry[]),
      orgsApi.list().then((r) => (r.data as OrgLite[]) || []).catch(() => [] as OrgLite[]),
    ]).then(([entries, orgList]) => {
      const map: Record<string, EnvVarResolveEntry["configured"]> = {};
      for (const e of entries) map[e.key] = e.configured;
      setConfigured(map);
      setOrgs(orgList);
      setLoading(false);
    });
  }, [open, required]);

  const openForm = (key: string) => {
    setForms((f) => ({
      ...f,
      [key]: { open: true, scope: orgs.length ? "org" : "user", name: key, value: "", busy: false },
    }));
  };

  const save = async (key: string) => {
    const form = forms[key];
    if (!form || !form.value.trim()) { toast.error("Enter a value."); return; }
    setForms((f) => ({ ...f, [key]: { ...form, busy: true } }));
    try {
      const orgId = form.scope === "org" ? orgs[0]?.id : undefined;
      const created = await envVarsApi.create({
        scope: form.scope, org_id: orgId, key, name: form.name.trim() || key, value: form.value,
      });
      setConfigured((c) => ({
        ...c,
        [key]: [...(c[key] || []), { id: created.data.id, scope: form.scope, name: created.data.name, org_id: orgId || null }],
      }));
      setForms((f) => ({ ...f, [key]: { ...form, open: false, busy: false, value: "" } }));
      toast.success(`${key} saved`);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Save failed");
      setForms((f) => ({ ...f, [key]: { ...form, busy: false } }));
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-full max-w-md bg-card border border-border rounded-xl shadow-lg p-5 space-y-4 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-full bg-primary/10 shrink-0 mt-0.5">
              <KeyRound className="w-4 h-4 text-primary" />
            </div>
            <div>
              <Dialog.Title className="text-sm font-semibold">Configure credentials</Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {label ? `“${label}” ` : "These tools "}need API keys / secrets. Set them once
                here (shared with your org, or just for you) — no server <code>.env</code> needed.
                Already-set values are reused automatically.
              </Dialog.Description>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-6 text-muted-foreground text-xs">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Checking what&apos;s configured…
            </div>
          ) : (
            <div className="space-y-2 max-h-72 overflow-auto">
              {required.map((r) => {
                const set = configured[r.key] || [];
                const form = forms[r.key];
                return (
                  <div key={r.key} className="bg-background border border-border rounded-lg px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <code className="text-xs font-mono text-foreground/90 break-all">{r.key}</code>
                        <p className="text-[11px] text-muted-foreground truncate">{r.tools.join(", ")}</p>
                      </div>
                      {set.length > 0 ? (
                        <span className="flex items-center gap-1 text-xs text-emerald-400 shrink-0">
                          <Check className="w-3.5 h-3.5" /> {set.length === 1 ? "set" : `${set.length} set`}
                        </span>
                      ) : !form?.open ? (
                        <Button variant="outline" size="sm" className="shrink-0 h-7 text-xs" onClick={() => openForm(r.key)}>
                          <Plus className="w-3 h-3 mr-1" /> Add
                        </Button>
                      ) : null}
                    </div>
                    {set.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {set.map((s) => (
                          <span key={s.id} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                            {s.scope === "org" ? "org" : "personal"} · {s.name}
                          </span>
                        ))}
                        {!form?.open && (
                          <button className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground"
                                  onClick={() => openForm(r.key)}>
                            + another
                          </button>
                        )}
                      </div>
                    )}
                    {form?.open && (
                      <div className="mt-2 space-y-2">
                        <div className="flex gap-2">
                          {orgs.length > 0 && (
                            <select
                              className="text-xs bg-background border border-border rounded px-2 py-1"
                              value={form.scope}
                              onChange={(e) => setForms((f) => ({ ...f, [r.key]: { ...form, scope: e.target.value as "org" | "user" } }))}
                            >
                              <option value="org">Org: {orgs[0].name}</option>
                              <option value="user">Personal</option>
                            </select>
                          )}
                          <input
                            className="flex-1 text-xs bg-background border border-border rounded px-2 py-1 font-mono"
                            placeholder="name (for duplicates)"
                            value={form.name}
                            onChange={(e) => setForms((f) => ({ ...f, [r.key]: { ...form, name: e.target.value } }))}
                          />
                        </div>
                        <div className="flex gap-2">
                          <input
                            type="password"
                            className="flex-1 text-xs bg-background border border-border rounded px-2 py-1 font-mono"
                            placeholder="value (secret)"
                            value={form.value}
                            onChange={(e) => setForms((f) => ({ ...f, [r.key]: { ...form, value: e.target.value } }))}
                            onKeyDown={(e) => { if (e.key === "Enter") save(r.key); }}
                          />
                          <Button size="sm" className="h-7 text-xs" disabled={form.busy} onClick={() => save(r.key)}>
                            {form.busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex justify-end pt-1">
            <Button size="sm" onClick={onClose}>Done</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
