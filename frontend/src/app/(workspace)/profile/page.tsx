"use client";
import { useState, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usersApi, userApiKeysApi, backupApi, totpApi, profileFactsApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { useUIModeStore, UIMode } from "@/store/ui-mode";
import { useOnboardingStore } from "@/store/onboarding";
import { cn, copyToClipboard } from "@/lib/utils";
import { Save, Eye, EyeOff, Pencil, Plus, Trash2, User, Loader2, GripVertical, Lock, Key, Copy, Check, ShieldAlert, ToggleLeft, ToggleRight, RefreshCw, Download, Upload, Database, Monitor, Layers } from "lucide-react";
import toast from "react-hot-toast";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ProfileFactsEditor } from "@/components/profile/ProfileFactsEditor";

type Tab = "profile" | "interface" | "memory" | "contact" | "security" | "apikeys" | "backup" | "admin";

interface ContactRow {
  key: string;
  value: string;
}

const PRESET_EMOJI = [
  "🧑", "👤", "🙂", "😎", "🤖", "🦊", "🐱", "🐶", "🦁", "🐻",
  "🦅", "🌟", "🚀", "💡", "🎯", "🔥", "⚡", "🌈", "🎨", "🏔️",
];

const PRESET_CONTACT_KEYS = ["Website", "LinkedIn", "Twitter / X", "GitHub", "Phone", "Email", "Telegram", "Discord", "Company", "Role"];

interface ApiKey { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null; }
interface AdminUser { id: string; email: string; full_name: string; is_active: boolean; is_superuser: boolean; }

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function MarketplaceKeySection() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [inputKey, setInputKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [showInput, setShowInput] = useState(false);

  useEffect(() => {
    usersApi.getMarketplaceKey().then((r) => setConfigured(r.data.configured)).catch(() => setConfigured(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await usersApi.setMarketplaceKey(inputKey.trim());
      setConfigured(!!inputKey.trim());
      setInputKey("");
      setShowInput(false);
      toast.success(inputKey.trim() ? "Marketplace API key saved" : "Key cleared");
    } catch {
      toast.error("Failed to save key");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-t border-border pt-6 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-foreground">Nexora Marketplace API Key</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Paste your personal API key from{" "}
            <span className="text-primary">marketplace.nexora.parendum.com → Settings</span>
            {" "}to access private packages via Import URL.
          </p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${configured ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-muted text-muted-foreground border-border"}`}>
          {configured === null ? "…" : configured ? "Connected" : "Not set"}
        </span>
      </div>
      {!showInput ? (
        <button
          onClick={() => setShowInput(true)}
          className="text-xs text-primary hover:underline"
        >
          {configured ? "Update key" : "Add key"}
        </button>
      ) : (
        <div className="flex gap-2 max-w-md">
          <input
            type="password"
            value={inputKey}
            onChange={(e) => setInputKey(e.target.value)}
            placeholder="nmk_…"
            className="flex-1 px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono"
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
          />
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
          </button>
          <button
            onClick={() => { setShowInput(false); setInputKey(""); }}
            className="px-3 py-2 text-sm border border-border rounded-md text-muted-foreground hover:text-foreground transition-colors"
          >
            Cancel
          </button>
          {configured && (
            <button
              onClick={() => { setInputKey(""); handleSave(); }}
              className="px-3 py-2 text-sm text-destructive border border-destructive/30 rounded-md hover:bg-destructive/10 transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function BackupTab({ isSuperuser }: { isSuperuser: boolean }) {
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingAll, setExportingAll] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleExport() {
    setExporting(true);
    try {
      const res = await backupApi.exportMine();
      const cd = (res as any).headers?.["content-disposition"] || "";
      const match = cd.match(/filename="(.+?)"/);
      const filename = match ? match[1] : `nexora_backup_${Date.now()}.json`;
      downloadBlob(res.data, filename);
      toast.success("Backup downloaded");
    } catch {
      toast.error("Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleExportAll() {
    setExportingAll(true);
    try {
      const res = await backupApi.exportAll();
      const cd = (res as any).headers?.["content-disposition"] || "";
      const match = cd.match(/filename="(.+?)"/);
      const filename = match ? match[1] : `nexora_admin_backup_${Date.now()}.json`;
      downloadBlob(res.data, filename);
      toast.success("Full system backup downloaded");
    } catch {
      toast.error("Admin export failed");
    } finally {
      setExportingAll(false);
    }
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      const res = await backupApi.importMine(payload);
      const fields: string[] = (res as any).data?.restored_fields ?? [];
      toast.success(`Restored: ${fields.join(", ") || "nothing changed"}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Import failed — check file format");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-8">
      {/* Personal backup */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">My Profile Backup</h3>
        <p className="text-sm text-muted-foreground">
          Export your profile data (name, avatar, AI memory, contact info, API key metadata).
          Sensitive values like passwords and raw API keys are never included.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
          >
            {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            Export my backup
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-border rounded-md hover:bg-accent disabled:opacity-50"
          >
            {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            Import backup
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={handleImportFile}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Import restores profile fields only. Email and password are not overwritten.
        </p>
      </div>

      {/* Admin backup — superusers only */}
      {isSuperuser && (
        <div className="space-y-3 pt-4 border-t border-border">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-amber-500" />
            <h3 className="text-sm font-semibold">Full System Backup</h3>
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-600 dark:text-amber-400">superuser</span>
          </div>
          <p className="text-sm text-muted-foreground">
            Export all users&apos; profiles, API key metadata, and org list in a single JSON file.
            Raw keys, passwords, and hashes are never included.
          </p>
          <button
            onClick={handleExportAll}
            disabled={exportingAll}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 text-white rounded-md hover:bg-amber-700 disabled:opacity-50"
          >
            {exportingAll ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
            Export full system backup
          </button>
        </div>
      )}
    </div>
  );
}

function TotpSection() {
  const [step, setStep] = useState<"idle" | "setup" | "verify" | "backup" | "disable">("idle");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [qrB64, setQrB64] = useState("");
  const [secret, setSecret] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    totpApi.status().then((r) => setEnabled(r.data.enabled)).catch(() => {});
  }, []);

  const startSetup = async () => {
    setWorking(true);
    try {
      const r = await totpApi.setup();
      setQrB64(r.data.qr_code_b64);
      setSecret(r.data.secret);
      setBackupCodes(r.data.backup_codes);
      setStep("setup");
    } catch { toast.error("Failed to start 2FA setup"); }
    finally { setWorking(false); }
  };

  const confirmSetup = async () => {
    setWorking(true);
    try {
      const r = await totpApi.verifySetup(code);
      setBackupCodes(r.data.backup_codes);
      setEnabled(true);
      setStep("backup");
      setCode("");
      toast.success("2FA enabled");
    } catch (err: any) { toast.error(err.response?.data?.detail || "Invalid code"); }
    finally { setWorking(false); }
  };

  const disableTotp = async () => {
    setWorking(true);
    try {
      await totpApi.disable(code);
      setEnabled(false);
      setStep("idle");
      setCode("");
      toast.success("2FA disabled");
    } catch (err: any) { toast.error(err.response?.data?.detail || "Invalid code"); }
    finally { setWorking(false); }
  };

  if (enabled === null) return null;

  return (
    <div className="pt-6 border-t border-border space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Two-factor authentication</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {enabled ? "2FA is active. Your account requires a code on login." : "Add a second layer of security to your account."}
          </p>
        </div>
        <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium border", enabled ? "text-green-400 bg-green-400/10 border-green-400/20" : "text-muted-foreground bg-muted/30 border-border")}>
          {enabled ? "Enabled" : "Disabled"}
        </span>
      </div>

      {step === "idle" && !enabled && (
        <button onClick={startSetup} disabled={working} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50">
          {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldAlert className="w-3.5 h-3.5" />}
          Enable 2FA
        </button>
      )}

      {step === "idle" && enabled && (
        <button onClick={() => setStep("disable")} className="flex items-center gap-2 px-4 py-2 text-sm border border-destructive text-destructive rounded-md hover:bg-destructive/10 transition-colors">
          Disable 2FA
        </button>
      )}

      {step === "setup" && (
        <div className="space-y-4 max-w-sm">
          <p className="text-xs text-muted-foreground">Scan this QR code with Google Authenticator or any TOTP app, then enter the 6-digit code below.</p>
          {qrB64 && <img src={`data:image/png;base64,${qrB64}`} alt="TOTP QR code" className="w-40 h-40 rounded-lg border border-border" />}
          <p className="text-xs text-muted-foreground font-mono bg-muted/30 px-3 py-2 rounded-md break-all">{secret}</p>
          <input
            type="text" inputMode="numeric" maxLength={6} placeholder="000000"
            value={code} onChange={(e) => setCode(e.target.value)}
            className="w-full px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono tracking-widest text-center"
            autoFocus
          />
          <div className="flex gap-2">
            <button onClick={confirmSetup} disabled={working || code.length < 6} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50">
              {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Verify & activate
            </button>
            <button onClick={() => { setStep("idle"); setCode(""); }} className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted/30 transition-colors">Cancel</button>
          </div>
        </div>
      )}

      {step === "backup" && (
        <div className="space-y-3 max-w-sm">
          <p className="text-xs text-amber-400 font-medium">Save these backup codes now — they won&apos;t be shown again.</p>
          <div className="grid grid-cols-2 gap-1.5">
            {backupCodes.map((c) => <code key={c} className="text-xs font-mono bg-muted/40 border border-border rounded px-2 py-1 text-center">{c}</code>)}
          </div>
          <button onClick={() => setStep("idle")} className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90">Done</button>
        </div>
      )}

      {step === "disable" && (
        <div className="space-y-3 max-w-sm">
          <p className="text-xs text-muted-foreground">Enter your current TOTP code or a backup code to disable 2FA.</p>
          <input
            type="text" inputMode="numeric" maxLength={8} placeholder="000000"
            value={code} onChange={(e) => setCode(e.target.value)}
            className="w-full px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono tracking-widest text-center"
            autoFocus
          />
          <div className="flex gap-2">
            <button onClick={disableTotp} disabled={working || code.length < 6} className="flex items-center gap-2 px-4 py-2 text-sm border border-destructive text-destructive rounded-md hover:bg-destructive/10 disabled:opacity-50">
              {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Disable 2FA
            </button>
            <button onClick={() => { setStep("idle"); setCode(""); }} className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted/30 transition-colors">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ProfilePage() {
  const { setUser, user: authUser } = useAuthStore();
  const { mode: uiMode, setMode: setUIMode } = useUIModeStore();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("profile");
  const { isActive: onboardingActive, currentStep } = useOnboardingStore();

  // Switch tab when onboarding banner advances through profile steps (0=profile, 1=interface, 2=contact)
  useEffect(() => {
    if (!onboardingActive) return;
    if (currentStep === 0) setTab("profile");
    else if (currentStep === 1) setTab("interface");
    else if (currentStep === 2) setTab("contact");
  }, [onboardingActive, currentStep]);

  // Always fetch fresh data — auth store may be stale
  const { data: freshUser, isLoading } = useQuery({
    queryKey: ["profile-me"],
    queryFn: () => usersApi.me().then((r) => r.data),
    staleTime: 0,
  });

  // Free-form notes now live as the reserved 'freeform' profile fact (single source of
  // truth shared with the AI's remember_user tool), not the legacy User.notes column.
  const { data: profileFacts } = useQuery({
    queryKey: ["profile-facts"],
    queryFn: () => profileFactsApi.list().then((r) => r.data),
    staleTime: 0,
  });
  const freeformFact = profileFacts?.find((f) => f.key === "freeform");

  // Profile tab state
  const [fullName, setFullName] = useState("");
  const [avatarEmoji, setAvatarEmoji] = useState("");
  const [customEmoji, setCustomEmoji] = useState("");

  // Memory tab state
  const [notes, setNotes] = useState("");
  const [previewMode, setPreviewMode] = useState(true);

  // Contact tab state
  const [rows, setRows] = useState<ContactRow[]>([]);
  const dragIndex = useRef<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);

  // Security tab state
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);

  useEffect(() => {
    if (freshUser) {
      setFullName(freshUser.full_name ?? "");
      setAvatarEmoji(freshUser.avatar_emoji ?? "");
      try {
        setRows(freshUser.contact_info ? JSON.parse(freshUser.contact_info) : []);
      } catch {
        setRows([]);
      }
      setUser(freshUser);
    }
  }, [freshUser?.id, freshUser?.contact_info]);

  // Load free-form notes from the 'freeform' fact (fallback to legacy notes if unset).
  useEffect(() => {
    setNotes(freeformFact?.value ?? freshUser?.notes ?? "");
  }, [freeformFact?.value, freshUser?.notes]);

  const mutation = useMutation({
    mutationFn: (data: Parameters<typeof usersApi.update>[0]) => usersApi.update(data).then((r) => r.data),
    onSuccess: (data) => {
      setUser(data);
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  const passwordMutation = useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      usersApi.changePassword(data),
    onSuccess: () => {
      toast.success("Password updated");
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    },
    onError: (err: any) =>
      toast.error(err?.response?.data?.detail || "Failed to update password"),
  });

  function savePassword() {
    if (!currentPw || !newPw || !confirmPw) {
      toast.error("Fill in all password fields");
      return;
    }
    if (newPw !== confirmPw) {
      toast.error("New passwords do not match");
      return;
    }
    passwordMutation.mutate({ current_password: currentPw, new_password: newPw });
  }

  // API Keys state
  const { data: apiKeys = [] } = useQuery<ApiKey[]>({
    queryKey: ["api-keys"],
    queryFn: () => userApiKeysApi.list().then((r) => r.data),
    enabled: tab === "apikeys",
  });
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);

  const createKeyMutation = useMutation({
    mutationFn: (name: string) => userApiKeysApi.create(name).then((r) => r.data),
    onSuccess: (data) => {
      setNewKeyValue(data.key);
      setNewKeyName("");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      copyToClipboard(data.key).then(() =>
        toast.success("API key created and copied to clipboard!", { icon: "🔑" })
      ).catch(() =>
        toast.success("API key created — copy it below", { icon: "🔑" })
      );
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to create key"),
  });

  const revokeKeyMutation = useMutation({
    mutationFn: (id: string) => userApiKeysApi.revoke(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["api-keys"] }); toast.success("Key revoked"); },
  });

  const rotateKeyMutation = useMutation({
    mutationFn: (id: string) => userApiKeysApi.rotate(id).then((r) => r.data),
    onSuccess: (data) => {
      setNewKeyValue(data.key);
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      copyToClipboard(data.key).then(() =>
        toast.success("Key rotated and copied to clipboard!", { icon: "🔄" })
      ).catch(() =>
        toast.success("Key rotated — copy the new value below", { icon: "🔄" })
      );
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to rotate key"),
  });

  function copyKey(key: string) {
    copyToClipboard(key).then(() => { setCopiedKey(true); setTimeout(() => setCopiedKey(false), 2000); });
  }

  // Admin state
  const { data: allUsers = [] } = useQuery<AdminUser[]>({
    queryKey: ["admin-users"],
    queryFn: () => usersApi.listAll().then((r) => r.data),
    enabled: tab === "admin" && !!authUser?.is_superuser,
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => usersApi.setActive(id, active),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  function saveProfile() {
    const emoji = customEmoji.trim() || avatarEmoji || null;
    mutation.mutate({ full_name: fullName.trim() || freshUser?.full_name, avatar_emoji: emoji });
  }

  const freeformMutation = useMutation({
    mutationFn: async () => {
      const v = notes.trim();
      if (v) await profileFactsApi.upsert("freeform", v);
      else if (freeformFact) await profileFactsApi.delete("freeform");
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-facts"] });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  function saveMemory() {
    freeformMutation.mutate();
  }

  function saveContact() {
    const clean = rows.filter((r) => r.key.trim());
    mutation.mutate({ contact_info: clean.length ? JSON.stringify(clean) : null });
  }

  function addRow(key = "") {
    setRows((prev) => [...prev, { key, value: "" }]);
  }

  function updateRow(i: number, field: "key" | "value", val: string) {
    setRows((prev) => prev.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  const displayEmoji = customEmoji.trim() || avatarEmoji;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-xl font-semibold">Profile</h1>
          {isLoading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
        </div>
        <p className="text-sm text-muted-foreground mb-6">
          Manage your identity and the context the AI knows about you.
        </p>

        {/* Tabs */}
        <div className="flex flex-wrap gap-1 mb-6 border-b border-border">
          {(["profile", "interface", "memory", "contact", "security", "apikeys", "backup", ...(authUser?.is_superuser ? ["admin"] : [])] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 pb-2 text-sm font-medium border-b-2 -mb-px transition-colors capitalize",
                tab === t
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {t === "memory" ? "AI Memory" : t === "contact" ? "Contact Info" : t === "security" ? "Security" : t === "apikeys" ? "API Keys" : t === "backup" ? "Backup" : t === "admin" ? "Admin" : t === "interface" ? "Interface" : "Profile"}
            </button>
          ))}
        </div>

        {/* ── Profile Tab ── */}
        {tab === "profile" && (
          <div className="space-y-6">
            {/* Avatar */}
            <div className="space-y-3">
              <label className="text-sm font-medium">Avatar</label>
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-accent flex items-center justify-center text-3xl shrink-0">
                  {displayEmoji || <User className="w-7 h-7 text-muted-foreground" />}
                </div>
                <div className="flex-1 space-y-2">
                  <input
                    value={customEmoji}
                    onChange={(e) => setCustomEmoji(e.target.value)}
                    placeholder="Paste any emoji…"
                    maxLength={4}
                    className="w-full px-3 py-1.5 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring"
                  />
                  <div className="flex flex-wrap gap-1.5">
                    {PRESET_EMOJI.map((e) => (
                      <button
                        key={e}
                        onClick={() => { setAvatarEmoji(e); setCustomEmoji(""); }}
                        className={cn(
                          "w-8 h-8 rounded-md flex items-center justify-center text-lg transition-colors hover:bg-accent",
                          avatarEmoji === e && !customEmoji && "bg-accent ring-1 ring-primary"
                        )}
                      >
                        {e}
                      </button>
                    ))}
                    {(avatarEmoji || customEmoji) && (
                      <button
                        onClick={() => { setAvatarEmoji(""); setCustomEmoji(""); }}
                        className="px-2 h-8 rounded-md text-xs text-muted-foreground hover:bg-accent"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Display name */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Display name</label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            {/* Email (read-only) */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">Email</label>
              <div className="px-3 py-2 text-sm bg-muted/40 border border-border rounded-md text-muted-foreground">
                {freshUser?.email}
              </div>
            </div>

            {/* Telegram link status */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">Telegram</label>
              {freshUser?.telegram_user_id ? (
                <div className="flex items-center gap-2 px-3 py-2 text-sm bg-muted/40 border border-border rounded-md">
                  <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                  <span className="text-muted-foreground">Linked (ID: {freshUser.telegram_user_id})</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3 py-2 text-sm bg-muted/40 border border-border rounded-md text-muted-foreground">
                  <span className="w-2 h-2 rounded-full bg-muted-foreground/40 shrink-0" />
                  Not linked — send a message to the Nexora bot on Telegram and your profile will auto-connect.
                </div>
              )}
            </div>

            <button
              onClick={saveProfile}
              disabled={mutation.isPending}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              Save profile
            </button>
          </div>
        )}

        {/* ── Interface Tab ── */}
        {tab === "interface" && (
          <div className="space-y-6">
            <div>
              <p className="text-sm text-muted-foreground">
                Choose how Nexora presents itself. Switch anytime — your preference is saved per device.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {(["simple", "advanced"] as UIMode[]).map((m) => {
                const isSelected = uiMode === m;
                return (
                  <button
                    key={m}
                    onClick={() => setUIMode(m)}
                    className={cn(
                      "text-left rounded-xl border-2 p-5 transition-all",
                      isSelected
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/40 hover:bg-accent/30"
                    )}
                  >
                    <div className="flex items-center gap-3 mb-3">
                      {m === "simple"
                        ? <Monitor className="w-5 h-5 text-primary shrink-0" />
                        : <Layers className="w-5 h-5 text-primary shrink-0" />
                      }
                      <span className="font-semibold text-sm capitalize">{m}</span>
                      {isSelected && (
                        <span className="ml-auto text-[10px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">Active</span>
                      )}
                    </div>
                    {m === "simple" ? (
                      <ul className="space-y-1.5 text-xs text-muted-foreground">
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Full chat list</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Tasks, Issues, Projects, Channels, Schedules</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Live active-agent workflow view</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Focused, distraction-free chat</li>
                      </ul>
                    ) : (
                      <ul className="space-y-1.5 text-xs text-muted-foreground">
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Full management suite (Agents, Personas, Skills, Tools, MCP)</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Sub-agent activity panel in chat</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Event logs &amp; chat notes</li>
                        <li className="flex items-start gap-1.5"><Check className="w-3 h-3 text-primary shrink-0 mt-0.5" />Full access to all configuration</li>
                      </ul>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* ── AI Memory Tab ── */}
        {tab === "memory" && (
          <div className="space-y-4">
            <ProfileFactsEditor />
            <div className="flex items-start justify-between gap-4">
              <p className="text-sm text-muted-foreground">
                Free-form notes the AI has gathered about you — or that you've written yourself. Used as context when the AI interacts with you.
              </p>
              <button
                onClick={() => setPreviewMode((v) => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-md hover:bg-accent shrink-0"
              >
                {previewMode ? <Pencil className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                {previewMode ? "Edit" : "Preview"}
              </button>
            </div>

            {previewMode ? (
              <div className="min-h-[320px] p-4 border border-border rounded-md bg-muted/20 prose prose-sm dark:prose-invert max-w-none text-sm">
                {notes.trim() ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{notes}</ReactMarkdown>
                ) : (
                  <p className="text-muted-foreground italic">Nothing here yet.</p>
                )}
              </div>
            ) : (
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={16}
                placeholder={`# About me\n\nWrite anything useful for the AI to know — your preferences, role, timezone, how you like to communicate…`}
                className="w-full px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono resize-y"
              />
            )}

            <button
              onClick={saveMemory}
              disabled={freeformMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              Save notes
            </button>
          </div>
        )}

        {/* ── Contact Info Tab ── */}
        {tab === "contact" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Social links, phone numbers, and any other contact details you want the AI to know about.
            </p>

            <div className="space-y-1.5">
              {rows.map((row, i) => (
                <div
                  key={i}
                  draggable
                  onDragStart={() => { dragIndex.current = i; }}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(i); }}
                  onDragLeave={() => setDragOver(null)}
                  onDrop={() => {
                    const from = dragIndex.current;
                    if (from === null || from === i) { setDragOver(null); return; }
                    const next = [...rows];
                    const [item] = next.splice(from, 1);
                    next.splice(i, 0, item);
                    setRows(next);
                    dragIndex.current = null;
                    setDragOver(null);
                  }}
                  onDragEnd={() => { dragIndex.current = null; setDragOver(null); }}
                  className={cn(
                    "flex gap-2 items-center rounded-md transition-colors",
                    dragOver === i && "bg-accent/50"
                  )}
                >
                  <div className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground/40 hover:text-muted-foreground shrink-0">
                    <GripVertical className="w-3.5 h-3.5" />
                  </div>
                  <input
                    value={row.key}
                    onChange={(e) => updateRow(i, "key", e.target.value)}
                    placeholder="Label"
                    className="w-36 shrink-0 px-3 py-1.5 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring"
                  />
                  <input
                    value={row.value}
                    onChange={(e) => updateRow(i, "value", e.target.value)}
                    placeholder="Value"
                    className="flex-1 px-3 py-1.5 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring"
                  />
                  <button
                    onClick={() => removeRow(i)}
                    className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-destructive shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>

            {/* Quick-add presets + custom row */}
            <div className="flex flex-wrap gap-1.5">
              {PRESET_CONTACT_KEYS.filter((k) => !rows.some((r) => r.key === k)).map((k) => (
                <button
                  key={k}
                  onClick={() => addRow(k)}
                  className="flex items-center gap-1 px-2 py-1 text-xs border border-dashed border-border rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
                >
                  <Plus className="w-3 h-3" />
                  {k}
                </button>
              ))}
              <button
                onClick={() => addRow("")}
                className="flex items-center gap-1 px-2 py-1 text-xs border border-dashed border-border rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
              >
                <Plus className="w-3 h-3" />
                Custom
              </button>
            </div>

            <button
              onClick={saveContact}
              disabled={mutation.isPending}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              Save contact info
            </button>
          </div>
        )}

        {/* ── Security Tab ── */}
        {tab === "security" && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 p-3 rounded-lg bg-muted/30 border border-border">
              <Lock className="w-4 h-4 text-muted-foreground shrink-0" />
              <p className="text-sm text-muted-foreground">
                Change your account password. You&apos;ll need to enter your current password to confirm.
              </p>
            </div>

            <div className="space-y-4 max-w-sm">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Current password</label>
                <div className="relative">
                  <input
                    type={showCurrentPw ? "text" : "password"}
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3 py-2 pr-9 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPw((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showCurrentPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium">New password</label>
                <div className="relative">
                  <input
                    type={showNewPw ? "text" : "password"}
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3 py-2 pr-9 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPw((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showNewPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">Min. 8 characters with uppercase, lowercase, and a digit.</p>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium">Confirm new password</label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  placeholder="••••••••"
                  className={cn(
                    "w-full px-3 py-2 text-sm bg-input border rounded-md outline-none focus:ring-1 focus:ring-ring font-mono",
                    confirmPw && newPw && confirmPw !== newPw
                      ? "border-destructive focus:ring-destructive"
                      : "border-border"
                  )}
                />
                {confirmPw && newPw && confirmPw !== newPw && (
                  <p className="text-xs text-destructive">Passwords do not match</p>
                )}
              </div>
            </div>

            <button
              onClick={savePassword}
              disabled={passwordMutation.isPending || (!!confirmPw && !!newPw && confirmPw !== newPw)}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              {passwordMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Lock className="w-3.5 h-3.5" />}
              Update password
            </button>

            {/* ── Two-Factor Authentication ── */}
            <TotpSection />
          </div>
        )}

        {/* ── API Keys Tab ── */}
        {tab === "apikeys" && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 p-3 rounded-lg bg-muted/30 border border-border">
              <Key className="w-4 h-4 text-muted-foreground shrink-0" />
              <p className="text-sm text-muted-foreground">
                API keys let you authenticate to Nexora from scripts and external tools. Each key is shown only once.
              </p>
            </div>

            {/* Create new key */}
            <div className="flex gap-2 max-w-md">
              <input
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Key name (e.g. Home Assistant)"
                className="flex-1 px-3 py-2 text-sm bg-input border border-border rounded-md outline-none focus:ring-1 focus:ring-ring"
                onKeyDown={(e) => e.key === "Enter" && newKeyName.trim() && createKeyMutation.mutate(newKeyName.trim())}
              />
              <button
                onClick={() => newKeyName.trim() && createKeyMutation.mutate(newKeyName.trim())}
                disabled={createKeyMutation.isPending || !newKeyName.trim()}
                className="flex items-center gap-1.5 px-3 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
              >
                {createKeyMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                Create
              </button>
            </div>

            {/* New key reveal */}
            {newKeyValue && (
              <div className="p-3 rounded-lg border border-primary/30 bg-primary/5 space-y-2">
                <p className="text-xs font-medium text-primary">Copy your new API key — it won&apos;t be shown again.</p>
                <div className="flex gap-2 items-center">
                  <code className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1.5 break-all">{newKeyValue}</code>
                  <button onClick={() => copyKey(newKeyValue)} className="shrink-0 p-1.5 rounded-md border border-border hover:bg-accent">
                    {copiedKey ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <button onClick={() => setNewKeyValue(null)} className="text-xs text-muted-foreground hover:text-foreground">Dismiss</button>
              </div>
            )}

            {/* Keys list */}
            <div className="space-y-2">
              {apiKeys.length === 0 ? (
                <p className="text-sm text-muted-foreground">No API keys yet.</p>
              ) : (
                apiKeys.map((k) => (
                  <div key={k.id} className="flex items-center gap-3 p-3 border border-border rounded-lg">
                    <Key className="w-4 h-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{k.name}</p>
                      <p className="text-xs text-muted-foreground font-mono">{k.prefix}…</p>
                      <p className="text-xs text-muted-foreground/60">
                        Created {new Date(k.created_at).toLocaleDateString()}
                        {k.last_used_at && ` · Last used ${new Date(k.last_used_at).toLocaleDateString()}`}
                      </p>
                    </div>
                    <button
                      onClick={() => rotateKeyMutation.mutate(k.id)}
                      disabled={rotateKeyMutation.isPending}
                      title="Rotate key"
                      className="text-muted-foreground hover:text-primary transition-colors p-1.5 rounded-md hover:bg-accent"
                    >
                      {rotateKeyMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      onClick={() => revokeKeyMutation.mutate(k.id)}
                      disabled={revokeKeyMutation.isPending}
                      title="Revoke key"
                      className="text-muted-foreground hover:text-destructive transition-colors p-1.5 rounded-md hover:bg-accent"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>

            {/* Nexora Marketplace API Key */}
            <MarketplaceKeySection />
          </div>
        )}

        {/* ── Backup Tab ── */}
        {tab === "backup" && (
          <BackupTab isSuperuser={!!authUser?.is_superuser} />
        )}

        {/* ── Admin Tab (superusers only) ── */}
        {tab === "admin" && authUser?.is_superuser && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0" />
              <p className="text-sm text-amber-600 dark:text-amber-400">
                Admin panel — visible only to superusers. Changes take effect immediately.
              </p>
            </div>

            <div className="space-y-2">
              {allUsers.map((u) => (
                <div key={u.id} className="flex items-center gap-3 p-3 border border-border rounded-lg">
                  <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center shrink-0 text-sm">
                    <User className="w-4 h-4 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium truncate">{u.full_name}</p>
                      {u.is_superuser && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-600 dark:text-amber-400">superuser</span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{u.email}</p>
                  </div>
                  {u.id !== authUser?.id && (
                    <button
                      onClick={() => toggleActiveMutation.mutate({ id: u.id, active: !u.is_active })}
                      disabled={toggleActiveMutation.isPending}
                      className={cn(
                        "flex items-center gap-1 text-xs px-2 py-1 rounded-md border transition-colors",
                        u.is_active
                          ? "border-border text-muted-foreground hover:text-destructive hover:border-destructive/50"
                          : "border-green-500/30 text-green-600 hover:bg-green-500/10"
                      )}
                    >
                      {u.is_active ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
