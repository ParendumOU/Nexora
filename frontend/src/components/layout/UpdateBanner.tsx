"use client";
import { useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";

const GATEWAY_URL = process.env.NEXT_PUBLIC_NEXORA_GATEWAY_URL || "";

interface UpdateInfo {
  update_available: boolean;
  latest_version: string | null;
  current_version: string | null;
}

async function fetchCurrentVersion(): Promise<string | null> {
  try {
    const res = await fetch("/api/system/version");
    if (res.ok) {
      const data = await res.json();
      return data.version ?? null;
    }
  } catch {}
  return null;
}

async function fetchLatestVersion(): Promise<string | null> {
  if (!GATEWAY_URL) return null;
  try {
    const res = await fetch(
      `${GATEWAY_URL}/api/versions/latest?product=nexora`,
      { next: { revalidate: 0 } }
    );
    if (res.ok) {
      const data = await res.json();
      return data.version ?? null;
    }
  } catch {}
  return null;
}

export function UpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const check = async () => {
      const [current, latest] = await Promise.all([
        fetchCurrentVersion(),
        fetchLatestVersion(),
      ]);
      if (current && latest && current !== latest) {
        setInfo({ update_available: true, latest_version: latest, current_version: current });
      }
    };

    check();
    const interval = setInterval(check, 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (!info?.update_available || dismissed) return null;

  return (
    <div className="w-full bg-indigo-950 border-b border-indigo-800 px-4 py-2 flex items-center justify-between gap-4 shrink-0 z-50">
      <div className="flex items-center gap-2.5 text-sm text-indigo-200">
        <RefreshCw className="w-4 h-4 text-indigo-400 shrink-0" />
        <span>
          <span className="font-semibold text-indigo-100">Update available:</span>{" "}
          Nexora {info.latest_version} is ready.{" "}
          <a
            href="https://nexora.parendum.com/changelog"
            target="_blank"
            rel="noopener noreferrer"
            className="underline text-indigo-300 hover:text-indigo-100 transition-colors"
          >
            View changelog
          </a>
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <a
          href="https://gitlab.com/parendum/nexora/nexora/-/releases"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs font-semibold bg-indigo-700 hover:bg-indigo-600 text-indigo-100 px-3 py-1.5 rounded-lg transition-colors"
        >
          View release
        </a>
        <button
          onClick={() => setDismissed(true)}
          className="text-indigo-400 hover:text-indigo-200 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
