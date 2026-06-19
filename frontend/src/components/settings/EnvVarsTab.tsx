"use client";
import { useEffect, useMemo, useState } from "react";
import { KeyRound, Plus, Trash2, Loader2, Building2, User as UserIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { envVarsApi, orgsApi, type EnvVar } from "@/lib/api";
import toast from "react-hot-toast";

interface OrgLite { id: string; name: string }

/**
 * Manage org- and user-scoped environment variables (tool credentials).
 * Values are write-only: never displayed; you can replace or delete them.
 * Resolution at run time is org-first, then user — so an org value shadows a
 * personal one with the same key unless you remove it.
 */
export default function EnvVarsTab() {
  const [vars, setVars] = useState<EnvVar[]>([]);
  const [orgs, setOrgs] = useState<OrgLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ scope: "user" as "user" | "org", org_id: "", key: "", name: "", value: "", description: "" });
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [v, o] = await Promise.all([
        envVarsApi.list().then((r) => r.data.env_vars),
        orgsApi.list().then((r) => (r.data as OrgLite[]) || []).catch(() => []),
      ]);
      setVars(v);
      setOrgs(o);
      if (o.length && !form.org_id) setForm((f) => ({ ...f, org_id: o[0].id }));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const grouped = useMemo(() => ({
    org: vars.filter((v) => v.scope === "org"),
    user: vars.filter((v) => v.scope === "user"),
  }), [vars]);

  const save = async () => {
    if (!form.key.trim() || !form.value.trim()) { toast.error("Key and value are required."); return; }
    setBusy(true);
    try {
      await envVarsApi.create({
        scope: form.scope,
        org_id: form.scope === "org" ? form.org_id : undefined,
        key: form.key.trim(),
        name: (form.name.trim() || form.key.trim()),
        value: form.value,
        description: form.description.trim() || undefined,
      });
      toast.success(`${form.key.trim()} saved`);
      setForm((f) => ({ ...f, key: "", name: "", value: "", description: "" }));
      setAdding(false);
      load();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (v: EnvVar) => {
    if (!confirm(`Delete ${v.scope} variable "${v.name}" (${v.key})?`)) return;
    try {
      await envVarsApi.delete(v.id);
      setVars((vs) => vs.filter((x) => x.id !== v.id));
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  const Row = ({ v }: { v: EnvVar }) => (
    <div className="flex items-center justify-between gap-3 bg-background border border-border rounded-lg px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <code className="text-xs font-mono text-foreground/90 break-all">{v.key}</code>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">{v.name}</span>
        </div>
        {v.description && <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{v.description}</p>}
      </div>
      <button onClick={() => remove(v)} className="text-muted-foreground hover:text-destructive shrink-0" title="Delete">
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <KeyRound className="w-4 h-4 text-primary" /> Environment Variables
        </h3>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          Store API keys and secrets used by tools — no server <code>.env</code> needed. Org
          variables are shared with the whole organization; personal variables are just for you.
          At run time, an org value is used first, then a personal one. Values are write-only
          (never shown). Use a distinct <em>name</em> to keep more than one value for the same key
          (e.g. prod vs test).
        </p>
      </div>

      {!adding ? (
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus className="w-3.5 h-3.5 mr-1.5" /> Add variable
        </Button>
      ) : (
        <div className="bg-card border border-border rounded-lg p-4 space-y-3">
          <div className="flex gap-2 flex-wrap">
            <select className="text-xs bg-background border border-border rounded px-2 py-1.5"
              value={form.scope} onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value as "user" | "org" }))}>
              <option value="user">Personal</option>
              {orgs.length > 0 && <option value="org">Organization</option>}
            </select>
            {form.scope === "org" && orgs.length > 0 && (
              <select className="text-xs bg-background border border-border rounded px-2 py-1.5"
                value={form.org_id} onChange={(e) => setForm((f) => ({ ...f, org_id: e.target.value }))}>
                {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input className="text-xs bg-background border border-border rounded px-2 py-1.5 font-mono"
              placeholder="KEY (e.g. STRIPE_SECRET_KEY)" value={form.key}
              onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))} />
            <input className="text-xs bg-background border border-border rounded px-2 py-1.5 font-mono"
              placeholder="name (defaults to key)" value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <input type="password" className="w-full text-xs bg-background border border-border rounded px-2 py-1.5 font-mono"
            placeholder="value (secret)" value={form.value}
            onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} />
          <input className="w-full text-xs bg-background border border-border rounded px-2 py-1.5"
            placeholder="description (optional)" value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          <div className="flex gap-2 justify-end">
            <Button size="sm" variant="outline" onClick={() => setAdding(false)} disabled={busy}>Cancel</Button>
            <Button size="sm" onClick={save} disabled={busy}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center text-xs text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…</div>
      ) : (
        <div className="space-y-5">
          <div>
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
              <Building2 className="w-3.5 h-3.5" /> Organization {grouped.org.length > 0 && `(${grouped.org.length})`}
            </div>
            {grouped.org.length === 0 ? (
              <p className="text-xs text-muted-foreground/70">No org variables. (Requires org owner/admin to add.)</p>
            ) : (
              <div className="space-y-1.5">{grouped.org.map((v) => <Row key={v.id} v={v} />)}</div>
            )}
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
              <UserIcon className="w-3.5 h-3.5" /> Personal {grouped.user.length > 0 && `(${grouped.user.length})`}
            </div>
            {grouped.user.length === 0 ? (
              <p className="text-xs text-muted-foreground/70">No personal variables yet.</p>
            ) : (
              <div className="space-y-1.5">{grouped.user.map((v) => <Row key={v.id} v={v} />)}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
