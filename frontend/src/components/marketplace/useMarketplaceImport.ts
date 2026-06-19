"use client";
import { useCallback, useState } from "react";
import toast from "react-hot-toast";
import {
  marketplaceApi,
  type MarketplaceImportResult,
  type RiskAcknowledgmentRequired,
} from "@/lib/api";

/** Shape of an axios error carrying the import endpoint's JSON body. */
interface ImportAxiosError {
  response?: {
    status?: number;
    data?: {
      // FastAPI wraps HTTPException detail under a top-level `detail` key. For
      // the risk gate that detail is an object; for ordinary errors it's a string.
      detail?: RiskAcknowledgmentRequired | string;
    };
  };
}

function parseRiskGate(e: unknown): RiskAcknowledgmentRequired | null {
  const err = e as ImportAxiosError;
  if (err?.response?.status !== 409) return null;
  const detail = err.response?.data?.detail;
  if (detail && typeof detail === "object" && detail.error === "risk_acknowledgment_required") {
    return detail;
  }
  return null;
}

export interface UseMarketplaceImportOptions {
  /** Called once on a successful import (initial or after acknowledgment). */
  onSuccess?: (result: MarketplaceImportResult) => void;
}

/**
 * Encapsulates the marketplace import flow incl. the GitLab #158 risk gate:
 * - calls POST /marketplace/import
 * - on 409 `risk_acknowledgment_required`, opens the confirmation dialog
 *   (state exposed as `pendingRisk`); `confirmRisk()` re-imports with
 *   acknowledge_risk=true, `cancelRisk()` aborts
 * - on success, surfaces the third-party disclaimer subtly via a toast
 *
 * Render <RiskAckDialog risk={pendingRisk} busy={acknowledging}
 *   onConfirm={confirmRisk} onCancel={cancelRisk} /> alongside the caller.
 */
export function useMarketplaceImport({ onSuccess }: UseMarketplaceImportOptions = {}) {
  const [importing, setImporting] = useState(false);
  const [pendingRisk, setPendingRisk] = useState<RiskAcknowledgmentRequired | null>(null);
  const [pendingUrl, setPendingUrl] = useState<string>("");
  const [acknowledging, setAcknowledging] = useState(false);

  const handleSuccess = useCallback(
    (result: MarketplaceImportResult) => {
      toast.success(`${result.name} imported`);
      // Subtle third-party liability footnote — unobtrusive for standard/trusted
      // packages, slightly firmer when the user just acknowledged a risk.
      if (result.disclaimer) {
        toast("Third-party content — installed at your own risk.", {
          icon: "ℹ️",
          duration: result.risk_acknowledged ? 6000 : 4000,
          style: { fontSize: "12px" },
        });
      }
      onSuccess?.(result);
    },
    [onSuccess],
  );

  /** Run an import. Returns true if installed, false if it opened the risk gate
   *  or failed. */
  const runImport = useCallback(
    async (url: string, acknowledgeRisk = false): Promise<boolean> => {
      const target = url.trim();
      if (!target) return false;
      const setBusy = acknowledgeRisk ? setAcknowledging : setImporting;
      setBusy(true);
      try {
        const res = await marketplaceApi.importFromUrl(target, acknowledgeRisk);
        setPendingRisk(null);
        setPendingUrl("");
        handleSuccess(res.data);
        return true;
      } catch (e: unknown) {
        const gate = parseRiskGate(e);
        if (gate) {
          // Stash the URL so the dialog's confirm can re-call with the same target.
          setPendingUrl(target);
          setPendingRisk(gate);
          return false;
        }
        const err = e as ImportAxiosError;
        const detail = err?.response?.data?.detail;
        toast.error(typeof detail === "string" ? detail : "Import failed");
        return false;
      } finally {
        setBusy(false);
      }
    },
    [handleSuccess],
  );

  const confirmRisk = useCallback(() => {
    if (pendingUrl) void runImport(pendingUrl, true);
  }, [pendingUrl, runImport]);

  const cancelRisk = useCallback(() => {
    setPendingRisk(null);
    setPendingUrl("");
  }, []);

  return {
    /** In flight for the initial (non-acknowledged) import. */
    importing,
    /** In flight for the acknowledged re-import. */
    acknowledging,
    /** Non-null while the risk dialog should be open. */
    pendingRisk,
    /** Kick off an import. */
    runImport,
    /** Re-import the gated package with acknowledge_risk=true. */
    confirmRisk,
    /** Dismiss the risk gate without installing. */
    cancelRisk,
  };
}
