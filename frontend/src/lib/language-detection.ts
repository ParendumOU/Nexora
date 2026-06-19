// ── Language detection ────────────────────────────────────────────────────────

export function getLanguage(filename: string): string {
  const lower = filename.toLowerCase();
  const ext = lower.split(".").pop() ?? "";
  if (lower === "dockerfile" || lower.startsWith("dockerfile.")) return "bash";
  if (lower === "makefile" || lower === "gemfile" || lower === "rakefile") return "bash";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", go: "go", rs: "rust", java: "java",
    json: "json", yaml: "yaml", yml: "yaml",
    md: "markdown", mdx: "markdown",
    html: "html", htm: "html", xml: "xml", svg: "xml",
    css: "css", scss: "css", sass: "css", less: "css",
    sh: "bash", bash: "bash", zsh: "bash", fish: "bash",
    sql: "sql", rb: "bash", php: "javascript",
    toml: "bash", ini: "bash", env: "bash",
  };
  return map[ext] ?? "plaintext";
}
