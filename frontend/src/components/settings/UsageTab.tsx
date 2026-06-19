"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usageApi } from "@/lib/api";
import { ArrowDown, ArrowUp, Wrench, Loader2, BarChart2 } from "lucide-react";

interface UsageSummary {
  total_input_tokens: number;
  total_output_tokens: number;
  total_tool_calls: number;
  by_provider: Array<{
    provider: string;
    input_tokens: number;
    output_tokens: number;
  }>;
  by_model: Array<{
    model: string;
    input_tokens: number;
    output_tokens: number;
  }>;
  by_day: Array<{
    date: string;
    input_tokens: number;
    output_tokens: number;
  }>;
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtInt(n: number | string | null | undefined): string {
  return new Intl.NumberFormat(undefined, { useGrouping: true }).format(Number(n) || 0);
}

function TokenBarChart({ data }: { data: UsageSummary["by_day"] }) {
  if (data.length === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-10">
        No data for this period
      </div>
    );
  }

  const maxVal = Math.max(...data.map((d) => d.input_tokens + d.output_tokens));
  if (maxVal === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-10">
        No token data recorded for this period
      </div>
    );
  }

  const CHART_H = 96;

  return (
    <div>
      <div className="flex items-end gap-px" style={{ height: CHART_H }}>
        {data.map((d) => {
          const total = d.input_tokens + d.output_tokens;
          const barH = Math.max(2, Math.round((total / maxVal) * CHART_H));
          const inputH = total > 0 ? Math.round((d.input_tokens / total) * barH) : 0;
          const outputH = barH - inputH;
          return (
            <div
              key={d.date}
              className="flex-1 flex flex-col justify-end cursor-default"
              title={`${d.date} — in: ${fmt(d.input_tokens)}, out: ${fmt(d.output_tokens)}`}
            >
              <div style={{ height: inputH }} className="bg-blue-400/70 rounded-t-sm" />
              <div style={{ height: outputH }} className="bg-green-400/70" />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground mt-2">
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
      <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm bg-blue-400/70 shrink-0" /> Input tokens
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm bg-green-400/70 shrink-0" /> Output tokens
        </span>
      </div>
    </div>
  );
}

const PERIODS = [
  { label: "7d", value: 7 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
  { label: "1y", value: 365 },
];

export default function UsageTab() {
  const [period, setPeriod] = useState(30);
  const [breakdownView, setBreakdownView] = useState<"account" | "model">("account");

  const { data, isLoading } = useQuery<UsageSummary>({
    queryKey: ["usage-summary", period],
    queryFn: () => usageApi.summary({ period_days: period }).then((r) => r.data),
  });

  const total = data ? data.total_input_tokens + data.total_output_tokens : 0;
  const maxProviderTotal = data
    ? Math.max(...data.by_provider.map((p) => p.input_tokens + p.output_tokens), 1)
    : 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Usage</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Token consumption across your conversations</p>
        </div>
        <div className="flex items-center gap-0.5 bg-muted rounded-lg p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                period === p.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[
              { label: "Input tokens",  value: fmt(data.total_input_tokens),   Icon: ArrowDown, color: "text-blue-400" },
              { label: "Output tokens", value: fmt(data.total_output_tokens),  Icon: ArrowUp,   color: "text-green-400" },
              { label: "Tool calls",    value: fmtInt(data.total_tool_calls),  Icon: Wrench,    color: "text-orange-400" },
            ].map(({ label, value, Icon, color }) => (
              <div key={label} className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground mb-2">
                  <Icon className={`w-3 h-3 ${color}`} />
                  {label}
                </div>
                <div className="text-2xl font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-4">
              <BarChart2 className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="text-xs font-medium">Token usage over time</span>
            </div>
            <TokenBarChart data={data.by_day} />
          </div>

          {(data.by_provider.length > 0 || data.by_model?.length > 0) ? (
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center justify-between mb-4">
                <div className="text-xs font-medium">
                  {breakdownView === "account" ? "By account" : "By model"}
                </div>
                <div className="flex items-center gap-0.5 bg-muted rounded-md p-0.5">
                  {(["account", "model"] as const).map((v) => (
                    <button
                      key={v}
                      onClick={() => setBreakdownView(v)}
                      className={`px-2.5 py-0.5 text-[11px] rounded transition-colors ${
                        breakdownView === v
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {v === "account" ? "Account" : "Model"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-3">
                {breakdownView === "account" ? (() => {
                  const maxTotal = Math.max(...data.by_provider.map((p) => p.input_tokens + p.output_tokens), 1);
                  return [...data.by_provider]
                    .sort((a, b) => (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens))
                    .map((p) => {
                      const rowTotal = p.input_tokens + p.output_tokens;
                      const pct = (rowTotal / maxTotal) * 100;
                      return (
                        <div key={p.provider}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-medium truncate max-w-[180px]">{p.provider}</span>
                            <div className="flex gap-3 text-[10px] text-muted-foreground tabular-nums shrink-0">
                              <span>{fmt(p.input_tokens)} in</span>
                              <span>{fmt(p.output_tokens)} out</span>
                            </div>
                          </div>
                          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                            <div className="h-full bg-primary/50 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    });
                })() : (() => {
                  const rows = data.by_model ?? [];
                  const maxTotal = Math.max(...rows.map((m) => m.input_tokens + m.output_tokens), 1);
                  return [...rows]
                    .sort((a, b) => (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens))
                    .map((m) => {
                      const rowTotal = m.input_tokens + m.output_tokens;
                      const pct = (rowTotal / maxTotal) * 100;
                      return (
                        <div key={m.model}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-medium truncate max-w-[180px]">{m.model}</span>
                            <div className="flex gap-3 text-[10px] text-muted-foreground tabular-nums shrink-0">
                              <span>{fmt(m.input_tokens)} in</span>
                              <span>{fmt(m.output_tokens)} out</span>
                            </div>
                          </div>
                          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                            <div className="h-full bg-violet-400/50 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    });
                })()}
              </div>

              {total > 0 && (
                <div className="mt-5 pt-4 border-t border-border">
                  <div className="text-[10px] text-muted-foreground mb-1.5">Input vs output split</div>
                  <div className="flex h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-blue-400/70 transition-all"
                      style={{ width: `${(data.total_input_tokens / total) * 100}%` }}
                    />
                    <div className="bg-green-400/70 flex-1" />
                  </div>
                  <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                    <span>{Math.round((data.total_input_tokens / total) * 100)}% input</span>
                    <span>{Math.round((data.total_output_tokens / total) * 100)}% output</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-10 text-muted-foreground text-sm">
              No usage data for the selected period.
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
