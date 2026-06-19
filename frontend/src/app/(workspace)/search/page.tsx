"use client";
import { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, MessageSquare, Loader2, ArrowRight } from "lucide-react";
import { searchApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SearchResult {
  type: "chat" | "message";
  id: string;
  title: string;
  snippet: string;
  url: string;
  role?: string;
  created_at: string | null;
  chat_id?: string;
}

function SearchContent() {
  const router = useRouter();
  const params = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    inputRef.current?.focus();
    const q = params.get("q");
    if (q) runSearch(q);
  }, []);

  const runSearch = async (q: string) => {
    if (!q.trim()) { setResults([]); setSearched(false); return; }
    setLoading(true);
    setSearched(true);
    try {
      const res = await searchApi.search(q.trim());
      setResults(res.data.results ?? []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      router.replace(`/search?q=${encodeURIComponent(val)}`, { scroll: false });
      runSearch(val);
    }, 350);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  const chatHits = results.filter((r) => r.type === "chat");
  const msgHits = results.filter((r) => r.type === "message");

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 w-full">
      {/* Search input */}
      <form onSubmit={handleSubmit} className="relative mb-8">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          placeholder="Search chats and messages…"
          className="w-full pl-11 pr-4 py-3 text-sm bg-card border border-border rounded-xl outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
        />
        {loading && <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 animate-spin text-muted-foreground" />}
      </form>

      {/* Results */}
      {!searched && !query && (
        <div className="text-center py-16 text-muted-foreground text-sm">
          <Search className="w-10 h-10 mx-auto mb-3 opacity-20" />
          <p>Search across all your chats and messages</p>
        </div>
      )}

      {searched && !loading && results.length === 0 && (
        <div className="text-center py-16 text-muted-foreground text-sm">
          No results for <span className="font-medium text-foreground">&ldquo;{query}&rdquo;</span>
        </div>
      )}

      {chatHits.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2 px-1">Chats</h2>
          <div className="space-y-1">
            {chatHits.map((r) => (
              <button key={r.id} onClick={() => router.push(r.url)}
                className="w-full flex items-center gap-3 px-4 py-3 bg-card border border-border rounded-xl hover:border-primary/40 hover:bg-card/80 transition-all group text-left">
                <MessageSquare className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
                <span className="text-sm font-medium text-foreground flex-1 truncate">{r.title}</span>
                <ArrowRight className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
              </button>
            ))}
          </div>
        </section>
      )}

      {msgHits.length > 0 && (
        <section>
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2 px-1">Messages</h2>
          <div className="space-y-1">
            {msgHits.map((r) => (
              <button key={r.id} onClick={() => router.push(r.url)}
                className="w-full flex items-start gap-3 px-4 py-3 bg-card border border-border rounded-xl hover:border-primary/40 hover:bg-card/80 transition-all group text-left">
                <MessageSquare className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5 group-hover:text-primary transition-colors" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-muted-foreground mb-0.5 truncate">{r.title}</p>
                  <p className="text-sm text-foreground line-clamp-2 leading-relaxed">{r.snippet}</p>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5" />
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchContent />
    </Suspense>
  );
}
