"use client";
import { useState, useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { providersApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { Loader2, Zap, ChevronDown, ExternalLink, Copy, Check, HelpCircle } from "lucide-react";
import { PROVIDER_MODELS } from "@/lib/provider-models";
import { OAUTH_PROVIDERS, APIKEY_PROVIDERS, providerDef } from "./provider-definitions";

type Step = "configure" | "oauth_wait" | "done";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={copy} className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground">
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

function AddProviderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("configure");
  const [providerType, setProviderType] = useState("claude");
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelIsCustom, setModelIsCustom] = useState(false);
  const [showSteps, setShowSteps] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [deviceCode, setDeviceCode] = useState<string | null>(null);
  const [awaitingCode, setAwaitingCode] = useState(false);
  const [geminiCode, setGeminiCode] = useState("");
  const [logLines, setLogLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const urlOpenedRef = useRef(false);

  const def = providerDef(providerType);

  const reset = () => {
    setStep("configure");
    setProviderType("claude");
    setName(""); setApiKey(""); setBaseUrl(""); setModelName(""); setModelIsCustom(false); setShowSteps(false);
    setAuthUrl(null); setDeviceCode(null); setAwaitingCode(false);
    setGeminiCode(""); setLogLines([]); setLoading(false);
    urlOpenedRef.current = false;
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  useEffect(() => { setModelName(""); setModelIsCustom(false); setShowSteps(false); }, [providerType]);

  const handleClose = () => { reset(); onClose(); };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const completeOAuth = async (provider: string, accountName: string) => {
    let lastError: any = null;

    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        return await providersApi.oauthComplete(provider, accountName, {
          provider_type: provider,
          account_name: accountName,
          model_name: modelName || null,
        });
      } catch (err: any) {
        lastError = err;
        const detail = err.response?.data?.detail as string | undefined;
        const retryable = !detail || detail.includes("No credentials found");
        if (!retryable || attempt === 4) break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }

    throw lastError;
  };

  const startPolling = (provider: string, accountName: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await providersApi.oauthStatus(provider, accountName);
        const d = res.data;
        if (d.output?.length) setLogLines(d.output);
        if (d.auth_url && !urlOpenedRef.current) {
          setAuthUrl(d.auth_url);
          urlOpenedRef.current = true;
          window.open(d.auth_url, "_blank", "noopener,noreferrer");
        }
        if (d.device_code && !deviceCode) setDeviceCode(d.device_code);
        if (d.status === "awaiting_code") setAwaitingCode(true);

        if (d.status === "success") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          try {
            await completeOAuth(provider, accountName);
            qc.invalidateQueries({ queryKey: ["providers"] });
            toast.success(`${accountName} connected`);
            handleClose();
          } catch (err: any) {
            toast.error(err.response?.data?.detail || "Authentication succeeded, but saving the account failed");
            setStep("configure");
            setLoading(false);
          }
        } else if (["finished", "timeout"].includes(d.status)) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          toast.error(d.error || "Authentication failed or timed out");
          setStep("configure");
          setLoading(false);
        }
      } catch { /* ignore transient */ }
    }, 2000);
  };

  const handleOAuthConnect = async () => {
    if (!name.trim()) { toast.error("Give this account a name"); return; }
    setLoading(true);
    try {
      await providersApi.oauthStart({ provider_type: providerType, account_name: name, model_name: modelName || undefined });
      setStep("oauth_wait");
      startPolling(providerType, name);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Failed to start authentication");
      setLoading(false);
    }
  };

  const handleApiKeyAdd = async () => {
    if (!name.trim()) { toast.error("Give this account a name"); return; }
    setLoading(true);
    try {
      const creds: Record<string, string> = {};
      if (providerType === "ollama") {
        // no credentials needed
      } else {
        creds.api_key = apiKey;
      }
      await providersApi.create({
        name,
        provider_type: providerType,
        auth_type: providerType === "ollama" ? "none" : "apikey",
        credentials: creds,
        base_url: baseUrl || undefined,
        model_name: modelName || undefined,
      });
      qc.invalidateQueries({ queryKey: ["providers"] });
      toast.success("Account added");
      handleClose();
    } catch {
      toast.error("Failed to add account");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitGeminiCode = async () => {
    if (!geminiCode.trim()) return;
    const code = geminiCode.trim();
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await providersApi.oauthSubmitCode(providerType, name, code);
        setGeminiCode("");
        return;
      } catch (err: any) {
        if (attempt < 2 && err?.response?.status === 404) {
          await new Promise((r) => setTimeout(r, 1500));
          continue;
        }
        toast.error("Failed to submit code — try again");
        return;
      }
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && handleClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-sm animate-fade-in">

          {/* Header */}
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">
              {step === "configure" ? "Add Account" : "Connecting…"}
            </Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">
              {step === "configure"
                ? "Connect as many accounts as you want per provider."
                : `Authenticating ${name} via ${def.label}`}
            </p>
          </div>

          <div className="p-5 space-y-3">
            {/* ── Configure step ───────────────────────────────── */}
            {step === "configure" && (
              <>
                {/* Provider selector */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-muted-foreground">Provider</label>
                    {!def.oauth && (def.setup_steps?.length ?? 0) > 0 && (
                      <button
                        type="button"
                        onClick={() => setShowSteps((v) => !v)}
                        className={cn(
                          "flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5 transition-colors",
                          showSteps
                            ? "bg-primary/10 text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-accent"
                        )}
                      >
                        <HelpCircle className="w-3 h-3" />
                        How to get key
                      </button>
                    )}
                  </div>
                  <Select.Root value={providerType} onValueChange={setProviderType}>
                    <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">
                      <div className="flex items-center gap-2">
                        <span className={cn("w-2 h-2 rounded-full shrink-0", providerDef(providerType).dot)} />
                        <Select.Value />
                      </div>
                      <ChevronDown className="w-3.5 h-3.5 opacity-50 shrink-0" />
                    </Select.Trigger>
                    <Select.Content
                      position="popper"
                      sideOffset={4}
                      className="z-[200] w-[var(--radix-select-trigger-width)] max-h-72 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1"
                    >
                      <div className="px-2 py-1">
                        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">OAuth — no API key needed</p>
                      </div>
                      {OAUTH_PROVIDERS.map((t) => (
                        <Select.Item key={t.value} value={t.value}
                          className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent"
                        >
                          <span className={cn("w-2 h-2 rounded-full shrink-0", t.dot)} />
                          <Select.ItemText>{t.label}</Select.ItemText>
                          <span className="ml-auto text-[10px] text-primary">OAuth</span>
                        </Select.Item>
                      ))}
                      <div className="px-2 py-1 mt-1">
                        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">API Key</p>
                      </div>
                      {APIKEY_PROVIDERS.map((t) => (
                        <Select.Item key={t.value} value={t.value}
                          className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent"
                        >
                          <span className={cn("w-2 h-2 rounded-full shrink-0", t.dot)} />
                          <Select.ItemText>{t.label}</Select.ItemText>
                        </Select.Item>
                      ))}
                    </Select.Content>
                  </Select.Root>
                </div>

                {/* Setup steps guide */}
                {showSteps && def.setup_steps && def.setup_steps.length > 0 && (
                  <div className="rounded-md border border-border bg-accent/20 px-3 py-2.5 space-y-2">
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">How to get API key</p>
                    <ol className="space-y-1.5">
                      {def.setup_steps.map((step, i) => (
                        <li key={i} className="flex gap-2 text-xs">
                          <span className="text-muted-foreground/60 shrink-0 font-mono">{i + 1}.</span>
                          {step.url ? (
                            <a
                              href={step.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary hover:underline flex items-center gap-1"
                            >
                              {step.text}
                              <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                            </a>
                          ) : (
                            <span className="text-foreground/80">{step.text}</span>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Provider hint */}
                {def.hint && !showSteps && (
                  <p className="text-xs text-muted-foreground leading-relaxed bg-accent/30 rounded-md px-3 py-2">
                    {def.hint}
                  </p>
                )}

                {/* Account name */}
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">Account name</label>
                  <Input
                    placeholder={`${def.label} – Personal`}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="h-8 text-sm"
                    autoFocus
                  />
                </div>

                {/* API key field (non-OAuth, non-Ollama) */}
                {!def.oauth && providerType !== "ollama" && (
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-muted-foreground">{def.apiKeyLabel ?? "API Key"}</label>
                    <Input
                      type="password"
                      placeholder={def.apiKeyPlaceholder ?? "..."}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>
                )}

                {/* Base URL (Azure, Ollama, Custom) */}
                {(def.needsBaseUrl) && (
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      {providerType === "azure"
                        ? "Azure resource endpoint"
                        : providerType === "ollama"
                        ? "Ollama URL"
                        : "Base URL"}
                    </label>
                    <Input
                      placeholder={
                        providerType === "azure"
                          ? "https://myresource.openai.azure.com/openai/deployments/gpt-4o"
                          : providerType === "ollama"
                          ? "http://localhost:11434"
                          : "https://api.example.com/v1"
                      }
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>
                )}

                {/* Model name */}
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    Model <span className="text-muted-foreground/50">(optional)</span>
                  </label>
                  {(PROVIDER_MODELS[providerType]?.length ?? 0) > 0 && !modelIsCustom ? (
                    <Select.Root
                      value={modelName}
                      onValueChange={(v) => {
                        if (v === "__custom__") { setModelIsCustom(true); setModelName(""); }
                        else setModelName(v);
                      }}
                    >
                      <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">
                        <Select.Value placeholder={def.defaultModel ?? "Provider default"} />
                        <ChevronDown className="w-3.5 h-3.5 opacity-50 shrink-0" />
                      </Select.Trigger>
                      <Select.Content
                        position="popper"
                        sideOffset={4}
                        className="z-[200] w-[var(--radix-select-trigger-width)] max-h-60 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1"
                      >
                        {PROVIDER_MODELS[providerType].map((m) => (
                          <Select.Item
                            key={m}
                            value={m}
                            className="flex items-center justify-between px-3 py-1.5 text-xs rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent font-mono"
                          >
                            <Select.ItemText>{m}</Select.ItemText>
                          </Select.Item>
                        ))}
                        <Select.Item
                          value="__custom__"
                          className="flex items-center px-3 py-1.5 text-xs rounded-md cursor-pointer outline-none data-[highlighted]:bg-accent text-muted-foreground"
                        >
                          <Select.ItemText>Custom…</Select.ItemText>
                        </Select.Item>
                      </Select.Content>
                    </Select.Root>
                  ) : (
                    <div className="flex gap-1.5 items-center">
                      {modelIsCustom && (
                        <button
                          type="button"
                          onClick={() => { setModelIsCustom(false); setModelName(""); }}
                          className="shrink-0 text-xs text-muted-foreground hover:text-foreground px-1.5 py-1 rounded border border-border hover:bg-accent transition-colors"
                        >
                          ←
                        </button>
                      )}
                      <Input
                        placeholder={def.defaultModel ?? "model-name"}
                        value={modelName}
                        onChange={(e) => setModelName(e.target.value)}
                        className="h-8 text-sm"
                      />
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="flex gap-2 justify-end pt-1">
                  <Button variant="outline" size="sm" onClick={handleClose} disabled={loading}>Cancel</Button>
                  {def.oauth ? (
                    <Button size="sm" onClick={handleOAuthConnect} disabled={loading} className="gap-1.5">
                      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                      Connect with OAuth
                    </Button>
                  ) : (
                    <Button size="sm" onClick={handleApiKeyAdd} disabled={loading}>
                      {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Adding…</> : "Add Account"}
                    </Button>
                  )}
                </div>
              </>
            )}

            {/* ── OAuth wait step ───────────────────────────────── */}
            {step === "oauth_wait" && (
              <div className="space-y-3">
                {!authUrl && (
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-accent/30 border border-border">
                    <Loader2 className="w-4 h-4 animate-spin text-primary shrink-0" />
                    <div>
                      <p className="text-sm font-medium">Starting authentication…</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Launching {def.label} CLI</p>
                    </div>
                  </div>
                )}

                {/* Device code for Codex */}
                {deviceCode && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">Your device code</p>
                    <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-accent/40 border border-border font-mono">
                      <span className="flex-1 text-sm font-bold tracking-widest text-foreground">{deviceCode}</span>
                      <CopyButton text={deviceCode} />
                    </div>
                    <p className="text-xs text-muted-foreground">Enter this code on the page that opens.</p>
                  </div>
                )}

                {/* Auth URL */}
                {authUrl && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">Authentication page</p>
                    <div className="flex items-center gap-2">
                      <a
                        href={authUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-primary/30 bg-primary/5 text-sm text-primary hover:bg-primary/10 transition-colors min-w-0"
                      >
                        <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                        <span className="truncate text-xs">{authUrl}</span>
                      </a>
                      <CopyButton text={authUrl} />
                    </div>
                  </div>
                )}

                {/* Code input for Claude and Gemini */}
                {(awaitingCode || providerType === "gemini" || providerType === "claude") && authUrl && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">Authorization code</p>
                    <div className="flex gap-2">
                      <Input
                        placeholder={
                          providerType === "gemini"
                            ? "Paste code from codeassist.google.com/authcode"
                            : "Paste the code shown after authenticating"
                        }
                        value={geminiCode}
                        onChange={(e) => setGeminiCode(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSubmitGeminiCode()}
                        className="h-8 text-sm"
                        autoFocus
                      />
                      <Button size="sm" onClick={handleSubmitGeminiCode} disabled={!geminiCode.trim()}>Submit</Button>
                    </div>
                  </div>
                )}

                {/* Waiting status */}
                {authUrl && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    {providerType === "claude" && "Authenticate in the browser, then paste the code above…"}
                    {providerType === "gemini" && "Waiting for code submission…"}
                    {providerType === "codex" && "Waiting for device authorization…"}
                  </div>
                )}

                {/* Log output */}
                {logLines.length > 0 && (
                  <div className="max-h-24 overflow-y-auto rounded-lg bg-neutral-950 border border-border p-2.5 space-y-0.5">
                    {logLines.map((line, i) => (
                      <p key={i} className="font-mono text-xs text-muted-foreground leading-relaxed">{line}</p>
                    ))}
                  </div>
                )}

                <div className="flex justify-end pt-1">
                  <Button variant="outline" size="sm" onClick={handleClose}>Cancel</Button>
                </div>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default AddProviderDialog;
