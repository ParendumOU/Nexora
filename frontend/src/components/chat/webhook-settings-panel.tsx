"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Webhook, Loader2, CheckCircle } from "lucide-react";
import toast from "react-hot-toast";
import { chatsApi } from "@/lib/api";

interface WebhookSettings {
  webhook_url: string | null;
  sync_response: boolean;
  sync_timeout: number;
}

export function WebhookSettingsPanel({
  chatId,
  onClose,
}: {
  chatId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();

  const { data: chat, isLoading } = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => chatsApi.get(chatId).then((r) => r.data),
    enabled: !!chatId,
  });

  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [syncResponse, setSyncResponse] = useState(false);
  const [syncTimeout, setSyncTimeout] = useState(10);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (chat) {
      setWebhookUrl(chat.webhook_url ?? "");
      setWebhookSecret("");
      setSyncResponse(chat.sync_response ?? false);
      setSyncTimeout(chat.sync_timeout ?? 10);
    }
  }, [chat]);

  const save = useMutation({
    mutationFn: () =>
      chatsApi.updateWebhook(chatId, {
        webhook_url: webhookUrl.trim() || null,
        webhook_secret: webhookSecret.trim() || undefined,
        sync_response: syncResponse,
        sync_timeout: Math.max(1, Math.min(30, syncTimeout)),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chat", chatId] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      toast.success("Webhook settings saved");
    },
    onError: () => toast.error("Failed to save webhook settings"),
  });

  return (
    <div className="flex flex-col h-full w-80 border-l border-border bg-card shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Webhook className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Outbound Webhook</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="flex items-center justify-center flex-1">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Webhook URL */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Webhook URL
            </label>
            <input
              type="url"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://your-server.example.com/hook"
              className="w-full text-xs bg-muted/50 border border-border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary font-mono"
            />
            <p className="text-[10px] text-muted-foreground">
              Nexora will POST a JSON payload to this URL after each agent response.
            </p>
          </div>

          {/* Secret */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Signing secret{" "}
              <span className="font-normal text-muted-foreground/70">— optional</span>
            </label>
            <input
              type="password"
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
              placeholder="Leave blank to keep existing"
              className="w-full text-xs bg-muted/50 border border-border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary font-mono"
            />
            <p className="text-[10px] text-muted-foreground">
              When set, each request includes an{" "}
              <code className="bg-muted px-1 rounded">X-Nexora-Signature</code>{" "}
              header (HMAC-SHA256).
            </p>
          </div>

          {/* Divider */}
          <div className="border-t border-border" />

          {/* Sync response toggle */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium">Wait for response</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  When enabled, the agent awaits the webhook response and
                  injects it back into the conversation as context.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSyncResponse((v) => !v)}
                className={`shrink-0 w-9 h-5 rounded-full transition-colors ${
                  syncResponse ? "bg-primary" : "bg-muted"
                }`}
              >
                <div
                  className={`w-4 h-4 bg-white rounded-full shadow transition-transform mt-0.5 ${
                    syncResponse ? "translate-x-4 ml-0.5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            {/* Timeout input — only shown when sync is on */}
            {syncResponse && (
              <div className="space-y-1.5 pl-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Timeout{" "}
                  <span className="font-normal text-muted-foreground/70">
                    — seconds (1–30)
                  </span>
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={1}
                    max={30}
                    value={syncTimeout}
                    onChange={(e) => setSyncTimeout(Number(e.target.value))}
                    className="flex-1 accent-primary"
                  />
                  <span className="text-xs font-mono w-6 text-right tabular-nums">
                    {syncTimeout}s
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  If the endpoint does not respond within this time, a timeout
                  error is injected instead.
                </p>
              </div>
            )}
          </div>

          {/* Payload preview */}
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
              Payload
            </p>
            <pre className="text-[10px] font-mono bg-muted/60 rounded px-3 py-2.5 leading-relaxed text-muted-foreground overflow-x-auto">
              {`{
  "event": "message.completed",
  "chat_id": "<chat_id>",
  "message_id": "<message_id>",
  "content": "<agent reply>",
  "agent_id": "<agent_id | null>",
  "timestamp": "<ISO 8601>"
}`}
            </pre>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border shrink-0">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {save.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : saved ? (
            <CheckCircle className="w-3.5 h-3.5" />
          ) : null}
          {save.isPending ? "Saving…" : saved ? "Saved" : "Save settings"}
        </button>
      </div>
    </div>
  );
}
