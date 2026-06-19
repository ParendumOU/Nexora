"use client";
import { useState, useEffect } from "react";
import { useUIModeStore } from "@/store/ui-mode";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { providersApi, seedsApi, integrationsApi } from "@/lib/api";
import { useOnboardingStore } from "@/store/onboarding";
import * as Tabs from "@radix-ui/react-tabs";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import toast from "react-hot-toast";

import { ProviderItem } from "@/components/settings/provider-definitions";
import { IntegrationItem } from "@/components/settings/integration-types";
import { ChainData } from "@/components/settings/ChainBuilderDialog";

import AddProviderDialog from "@/components/settings/AddProviderDialog";
import EditProviderDialog from "@/components/settings/EditProviderDialog";
import ChainBuilderDialog from "@/components/settings/ChainBuilderDialog";
import AddIntegrationDialog from "@/components/settings/AddIntegrationDialog";
import EditIntegrationDialog from "@/components/settings/EditIntegrationDialog";
import AccountsTab from "@/components/settings/AccountsTab";
import ChainsTab from "@/components/settings/ChainsTab";
import IntegrationsTab from "@/components/settings/IntegrationsTab";
import SeedsTab from "@/components/settings/SeedsTab";
import UsageTab from "@/components/settings/UsageTab";
import ModelProfilesTab from "@/components/settings/ModelProfilesTab";
import ProviderTypesTab from "@/components/settings/ProviderTypesTab";
import AutomationsTab from "@/components/settings/AutomationsTab";
import DevicesTab from "@/components/settings/DevicesTab";
import BackupTab from "@/components/settings/BackupTab";
import EnvVarsTab from "@/components/settings/EnvVarsTab";
import MarketplaceUpdatesTab from "@/components/settings/MarketplaceUpdatesTab";
import { useAuthStore } from "@/store/auth";

interface SeedCatalogItem {
  type: string;
  key: string;
  name: string;
  description: string;
  category: string;
  source: "builtin" | "custom";
  is_builtin: boolean;
}

export default function SettingsPage() {
  const uiMode = useUIModeStore((s) => s.mode);
  const isSuperuser = useAuthStore((s) => s.user?.is_superuser);
  const [activeTab, setActiveTab] = useState("usage");
  const { isActive: onboardingActive, currentStep } = useOnboardingStore();

  // Switch tab when onboarding banner advances through settings steps (3=accounts, 4=models, 5=chains, 6=integrations)
  useEffect(() => {
    if (!onboardingActive) return;
    if (currentStep === 3) setActiveTab("accounts");
    else if (currentStep === 4) setActiveTab("models");
    else if (currentStep === 5) setActiveTab("chains");
    else if (currentStep === 6) setActiveTab("integrations");
  }, [onboardingActive, currentStep]);
  const [showAdd, setShowAdd] = useState(false);
  const [showChain, setShowChain] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ProviderItem | null>(null);
  const [editingChain, setEditingChain] = useState<ChainData | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [pendingPurge, setPendingPurge] = useState<{ id: string; name: string } | null>(null);
  const [pendingDeleteChain, setPendingDeleteChain] = useState<{ id: string; name: string } | null>(null);
  const [expandedChains, setExpandedChains] = useState<Set<string>>(new Set());
  const [seedImporting, setSeedImporting] = useState(false);
  const [seedTypeFilter, setSeedTypeFilter] = useState<"all" | "tool" | "skill" | "persona" | "agent">("all");
  const [missingDeps, setMissingDeps] = useState<Array<{ slug: string; key: string; name: string; type: string; version: string }>>([]);
  const [installingDeps, setInstallingDeps] = useState(false);
  const [depInstallResults, setDepInstallResults] = useState<{ installed: string[]; failed: string[] } | null>(null);
  const [showAddIntegration, setShowAddIntegration] = useState(false);
  const [editingIntegration, setEditingIntegration] = useState<IntegrationItem | null>(null);
  const [pendingDeleteIntegration, setPendingDeleteIntegration] = useState<{ id: string; name: string } | null>(null);
  const qc = useQueryClient();

  const { data: seedCatalog = [], isLoading: loadingSeeds } = useQuery<SeedCatalogItem[]>({
    queryKey: ["seeds-catalog"],
    queryFn: () => seedsApi.catalog().then((r) => r.data),
  });

  const deleteCustomSeed = useMutation({
    mutationFn: ({ type, key }: { type: string; key: string }) => seedsApi.deleteCustom(type, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seeds-catalog"] });
      toast.success("Custom seed deleted");
    },
    onError: () => toast.error("Failed to delete seed"),
  });

  const handleSeedImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSeedImporting(true);
    try {
      const res = await seedsApi.importZip(file);
      const { imported, skipped, missing_deps } = res.data;
      toast.success(`Imported ${imported.length} file(s)${skipped.length ? `, skipped ${skipped.length}` : ""}`);
      qc.invalidateQueries({ queryKey: ["seeds-catalog"] });
      if (missing_deps && missing_deps.length > 0) {
        setMissingDeps(missing_deps);
        setDepInstallResults(null);
      }
    } catch {
      toast.error("Import failed — check the ZIP structure");
    } finally {
      setSeedImporting(false);
      e.target.value = "";
    }
  };

  const handleInstallDeps = async () => {
    setInstallingDeps(true);
    try {
      const res = await seedsApi.installDeps(missingDeps);
      const { installed, failed } = res.data;
      setDepInstallResults({
        installed: installed.map((i: { name?: string; slug?: string }) => i.name || i.slug || ""),
        failed: failed.map((f: { slug?: string; reason?: string }) => `${f.slug}: ${f.reason}`),
      });
      if (installed.length > 0) {
        qc.invalidateQueries({ queryKey: ["seeds-catalog"] });
        toast.success(`Installed ${installed.length} dependenc${installed.length === 1 ? "y" : "ies"}`);
      }
      if (failed.length > 0) toast.error(`${failed.length} failed to install`);
    } catch {
      toast.error("Failed to install dependencies");
    } finally {
      setInstallingDeps(false);
    }
  };

  const handleExportAllCustom = async () => {
    const customSeeds = seedCatalog.filter((s) => s.source === "custom");
    if (customSeeds.length === 0) {
      toast.error("No custom seeds to export");
      return;
    }
    try {
      const res = await seedsApi.exportItems([{ type: "all_custom" }]);
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/zip" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "seeds_custom_export.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Export failed");
    }
  };

  const { data: integrationsList = [], isLoading: loadingIntegrations } = useQuery<IntegrationItem[]>({
    queryKey: ["integrations"],
    queryFn: () => integrationsApi.list().then((r) => r.data),
  });

  const deleteIntegration = useMutation({
    mutationFn: (id: string) => integrationsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["integrations"] }); toast.success("Integration removed"); setPendingDeleteIntegration(null); },
    onError: () => toast.error("Failed to delete integration"),
  });

  const setDefaultIntegration = useMutation({
    mutationFn: (id: string) => integrationsApi.setDefault(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["integrations"] }); toast.success("Set as default integration"); },
    onError: () => toast.error("Failed to set default"),
  });

  const { data: providers = [], isLoading: loadingProviders } = useQuery({
    queryKey: ["providers"],
    queryFn: () => providersApi.list().then((r) => r.data),
  });
  const { data: chains = [], isLoading: loadingChains } = useQuery({
    queryKey: ["chains"],
    queryFn: () => providersApi.chains().then((r) => r.data),
  });

  const deleteProvider = useMutation({
    mutationFn: (id: string) => providersApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); toast.success("Account removed"); setPendingDelete(null); },
    onError: () => toast.error("Failed to remove account"),
  });

  const restoreProvider = useMutation({
    mutationFn: (id: string) => providersApi.restore(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); toast.success("Account restored"); },
    onError: () => toast.error("Failed to restore account"),
  });

  const purgeProvider = useMutation({
    mutationFn: (id: string) => providersApi.purge(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); toast.success("Account permanently deleted"); setPendingPurge(null); },
    onError: () => toast.error("Failed to delete account"),
  });

  const deleteChainMutation = useMutation({
    mutationFn: (id: string) => providersApi.deleteChain(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["chains"] }); toast.success("Chain deleted"); setPendingDeleteChain(null); },
    onError: () => toast.error("Failed to delete chain"),
  });

  const toggleChainExpanded = (id: string) =>
    setExpandedChains((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });

  const grouped: Record<string, ProviderItem[]> = {};
  for (const p of providers as ProviderItem[]) {
    if (!grouped[p.provider_type]) grouped[p.provider_type] = [];
    grouped[p.provider_type].push(p);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="px-6 py-4 border-b border-border shrink-0">
        <h1 className="text-sm font-semibold">Settings</h1>
        <p className="text-xs text-muted-foreground mt-0.5">AI provider accounts and fallback chains</p>
      </div>

      <Tabs.Root value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
        <Tabs.List className="flex px-6 gap-0.5 border-b border-border shrink-0">
          {[["usage", "Usage"], ["accounts", "Accounts"], ["models", "Model Profiles"], ["chains", "Fallback Chains"], ["provider-types", "Provider Types"], ["integrations", "Integrations"], ["automations", "Automations"], ["env-vars", "Variables"], ["devices", "Devices"], ["updates", "Updates"], ["seeds", "Seed Library"], ["backup", "Backup"]]
            .filter(([v]) => uiMode === "advanced" || (v !== "provider-types" && v !== "seeds"))
            .filter(([v]) => v !== "backup" || isSuperuser)
            .map(([v, l]) => (
            <Tabs.Trigger key={v} value={v}
              className="px-3 py-2.5 text-xs font-medium text-muted-foreground data-[state=active]:text-foreground data-[state=active]:border-b-2 data-[state=active]:border-primary -mb-px transition-colors"
            >
              {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {/* ── Accounts ─────────────────────────────────────────────── */}
        <Tabs.Content value="accounts" className="flex-1 overflow-y-auto p-6 space-y-6">
          <AccountsTab
            loadingProviders={loadingProviders}
            providers={providers as ProviderItem[]}
            grouped={grouped}
            onAddAccount={() => setShowAdd(true)}
            onEditProvider={setEditingProvider}
            onDeleteProvider={setPendingDelete}
            onRestoreProvider={(id) => restoreProvider.mutate(id)}
            onPurgeProvider={setPendingPurge}
          />
        </Tabs.Content>

        {/* ── Chains ───────────────────────────────────────────────── */}
        <Tabs.Content value="chains" className="flex-1 overflow-y-auto p-6 space-y-6">
          <ChainsTab
            loadingChains={loadingChains}
            chains={chains as ChainData[]}
            providers={providers as ProviderItem[]}
            expandedChains={expandedChains}
            onNewChain={() => { setEditingChain(null); setShowChain(true); }}
            onEditChain={(chain) => { setEditingChain(chain); setShowChain(true); }}
            onDeleteChain={setPendingDeleteChain}
            onToggleExpanded={toggleChainExpanded}
          />
        </Tabs.Content>

        {/* ── Model Profiles ───────────────────────────────────── */}
        <Tabs.Content value="models" className="flex-1 overflow-y-auto p-6">
          <ModelProfilesTab />
        </Tabs.Content>

        {/* ── Provider Types ───────────────────────────────────── */}
        <Tabs.Content value="provider-types" className="flex-1 overflow-y-auto p-6">
          <ProviderTypesTab />
        </Tabs.Content>

        {/* ── Integrations ─────────────────────────────────────── */}
        <Tabs.Content value="integrations" className="flex-1 overflow-y-auto p-6 space-y-6">
          <IntegrationsTab
            loadingIntegrations={loadingIntegrations}
            integrationsList={integrationsList}
            setDefaultIntegrationPending={setDefaultIntegration.isPending}
            onAddIntegration={() => setShowAddIntegration(true)}
            onEditIntegration={setEditingIntegration}
            onDeleteIntegration={setPendingDeleteIntegration}
            onSetDefault={(id) => setDefaultIntegration.mutate(id)}
          />
        </Tabs.Content>

        {/* ── Automations ──────────────────────────────────────── */}
        <Tabs.Content value="automations" className="flex-1 overflow-y-auto p-6">
          <AutomationsTab />
        </Tabs.Content>

        {/* ── Usage ────────────────────────────────────────────── */}
        <Tabs.Content value="usage" className="flex-1 overflow-y-auto p-6">
          <UsageTab />
        </Tabs.Content>

        {/* ── Environment Variables ────────────────────────────── */}
        <Tabs.Content value="env-vars" className="flex-1 overflow-y-auto p-6">
          <EnvVarsTab />
        </Tabs.Content>

        {/* ── Devices ──────────────────────────────────────────── */}
        <Tabs.Content value="devices" className="flex-1 overflow-y-auto p-6">
          <DevicesTab />
        </Tabs.Content>

        {/* ── Marketplace updates ──────────────────────────────── */}
        <Tabs.Content value="updates" className="flex-1 overflow-y-auto p-6">
          <MarketplaceUpdatesTab />
        </Tabs.Content>

        {/* ── Backup ───────────────────────────────────────────── */}
        <Tabs.Content value="backup" className="flex-1 overflow-y-auto p-6">
          <BackupTab />
        </Tabs.Content>

        {/* ── Seed Library ─────────────────────────────────────── */}
        <Tabs.Content value="seeds" className="flex-1 overflow-y-auto p-6 space-y-6">
          <SeedsTab
            loadingSeeds={loadingSeeds}
            seedCatalog={seedCatalog}
            seedImporting={seedImporting}
            seedTypeFilter={seedTypeFilter}
            onSeedTypeFilter={setSeedTypeFilter}
            onSeedImport={handleSeedImport}
            onExportAllCustom={handleExportAllCustom}
            onDeleteCustomSeed={({ type, key }) => deleteCustomSeed.mutate({ type, key })}
            missingDeps={missingDeps}
            installingDeps={installingDeps}
            depInstallResults={depInstallResults}
            onInstallDeps={handleInstallDeps}
            onDismissDeps={() => { setMissingDeps([]); setDepInstallResults(null); }}
          />
        </Tabs.Content>
      </Tabs.Root>

      <AddIntegrationDialog open={showAddIntegration} onClose={() => setShowAddIntegration(false)} />
      <EditIntegrationDialog integration={editingIntegration} onClose={() => setEditingIntegration(null)} />
      <ConfirmDeleteDialog
        open={!!pendingDeleteIntegration}
        onClose={() => setPendingDeleteIntegration(null)}
        onConfirm={() => pendingDeleteIntegration && deleteIntegration.mutate(pendingDeleteIntegration.id)}
        loading={deleteIntegration.isPending}
        title="Remove integration?"
        description={`"${pendingDeleteIntegration?.name}" will be disconnected and its credentials removed.`}
        destroys={["Bot token / credentials", "Any channels currently using this account"]}
      />
      <AddProviderDialog open={showAdd} onClose={() => setShowAdd(false)} />
      <ChainBuilderDialog
        open={showChain}
        onClose={() => { setShowChain(false); setEditingChain(null); }}
        providers={providers as ProviderItem[]}
        editChain={editingChain ?? undefined}
      />
      <EditProviderDialog provider={editingProvider} onClose={() => setEditingProvider(null)} />
      <ConfirmDeleteDialog
        open={!!pendingDelete}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteProvider.mutate(pendingDelete.id)}
        loading={deleteProvider.isPending}
        title="Remove account?"
        description={`"${pendingDelete?.name}" will be disconnected and its credentials removed.`}
        destroys={["Authentication credentials and tokens", "This account from all fallback chains"]}
      />
      <ConfirmDeleteDialog
        open={!!pendingPurge}
        onClose={() => setPendingPurge(null)}
        onConfirm={() => pendingPurge && purgeProvider.mutate(pendingPurge.id)}
        loading={purgeProvider.isPending}
        title="Permanently delete account?"
        description={`"${pendingPurge?.name}" will be erased from the database. This cannot be undone.`}
        destroys={["All credentials and tokens", "Account row from database — unrecoverable"]}
      />
      <ConfirmDeleteDialog
        open={!!pendingDeleteChain}
        onClose={() => setPendingDeleteChain(null)}
        onConfirm={() => pendingDeleteChain && deleteChainMutation.mutate(pendingDeleteChain.id)}
        loading={deleteChainMutation.isPending}
        title="Delete chain?"
        description={`"${pendingDeleteChain?.name}" will be permanently removed.`}
        destroys={["All steps in this chain", "Any chats currently using this chain"]}
      />
    </div>
  );
}
