"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Smartphone, QrCode, Trash2, RefreshCw, Apple, Bot, X } from "lucide-react";
import toast from "react-hot-toast";
import { devicesApi } from "@/lib/api";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";

interface Device {
  id: string;
  name: string;
  platform: string;
  created_at: string;
  last_seen_at: string | null;
}

interface PairData {
  code: string;
  url: string;
  qr_b64: string;
  expires_in: number;
}

function relative(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function PlatformIcon({ platform }: { platform: string }) {
  if (platform === "ios") return <Apple className="w-4 h-4 text-muted-foreground" />;
  if (platform === "android") return <Bot className="w-4 h-4 text-emerald-400" />;
  return <Smartphone className="w-4 h-4 text-muted-foreground" />;
}

export default function DevicesTab() {
  const qc = useQueryClient();
  const [pair, setPair] = useState<PairData | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [pendingRevoke, setPendingRevoke] = useState<Device | null>(null);

  const { data: devices = [], isLoading } = useQuery<Device[]>({
    queryKey: ["devices"],
    queryFn: async () => (await devicesApi.list()).data,
    // While a QR is on screen, poll so a freshly-linked device pops in automatically.
    refetchInterval: pair ? 3000 : false,
  });

  const start = useMutation({
    mutationFn: async () => {
      const origin = typeof window !== "undefined" ? window.location.origin : undefined;
      return (await devicesApi.start(origin)).data as PairData;
    },
    onSuccess: (data) => {
      setPair(data);
      setSecondsLeft(data.expires_in);
    },
    onError: () => toast.error("Could not generate a pairing code"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => devicesApi.revoke(id),
    onSuccess: () => {
      toast.success("Device unlinked");
      qc.invalidateQueries({ queryKey: ["devices"] });
      setPendingRevoke(null);
    },
    onError: () => toast.error("Failed to unlink device"),
  });

  // Countdown + auto-expire the QR.
  useEffect(() => {
    if (!pair) return;
    if (secondsLeft <= 0) {
      setPair(null);
      return;
    }
    const t = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [pair, secondsLeft]);

  // Dismiss the QR once the device count grows (device linked successfully).
  const linkedCount = devices.length;
  const [baseline, setBaseline] = useState<number | null>(null);
  useEffect(() => {
    if (pair && baseline === null) setBaseline(linkedCount);
    if (pair && baseline !== null && linkedCount > baseline) {
      toast.success("Device linked!");
      setPair(null);
      setBaseline(null);
    }
    if (!pair) setBaseline(null);
  }, [pair, linkedCount, baseline]);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-sm font-semibold">Mobile devices</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Link the Nexora mobile app by scanning a QR code. Each device gets its own
          revocable access — unlinking one never signs out your other sessions.
        </p>
      </div>

      {/* Pairing panel */}
      {pair ? (
        <div className="rounded-xl border border-primary/30 bg-card p-6 flex flex-col items-center gap-4">
          <div className="flex items-center justify-between w-full">
            <span className="text-xs font-medium text-foreground">Scan with the Nexora app</span>
            <button
              onClick={() => setPair(null)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/png;base64,${pair.qr_b64}`}
            alt="Pairing QR code"
            className="w-52 h-52 rounded-lg bg-white p-2"
          />
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Or enter this code manually</p>
            <p className="text-lg font-mono font-semibold tracking-widest text-foreground mt-1">
              {pair.code}
            </p>
            <p className="text-[11px] text-muted-foreground mt-1">
              Expires in {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
            </p>
          </div>
        </div>
      ) : (
        <button
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {start.isPending ? <RefreshCw className="w-4 h-4 animate-spin" /> : <QrCode className="w-4 h-4" />}
          Link a new device
        </button>
      )}

      {/* Linked devices */}
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Linked devices {linkedCount > 0 ? `(${linkedCount})` : ""}
        </h3>
        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : devices.length === 0 ? (
          <p className="text-xs text-muted-foreground py-4 text-center border border-dashed border-border rounded-lg">
            No devices linked yet.
          </p>
        ) : (
          <div className="rounded-xl border border-border overflow-hidden divide-y divide-border">
            {devices.map((d) => (
              <div key={d.id} className="flex items-center gap-3 px-4 py-3">
                <PlatformIcon platform={d.platform} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground truncate">{d.name}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {d.platform} · last active {relative(d.last_seen_at)}
                  </p>
                </div>
                <button
                  onClick={() => setPendingRevoke(d)}
                  className="text-muted-foreground hover:text-red-400 transition-colors p-1"
                  title="Unlink device"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDeleteDialog
        open={!!pendingRevoke}
        onClose={() => setPendingRevoke(null)}
        onConfirm={() => pendingRevoke && revoke.mutate(pendingRevoke.id)}
        loading={revoke.isPending}
        title="Unlink this device?"
        description={`"${pendingRevoke?.name}" will lose access. It can be re-linked by scanning a new QR code.`}
        destroys={["The device's stored access token"]}
      />
    </div>
  );
}
