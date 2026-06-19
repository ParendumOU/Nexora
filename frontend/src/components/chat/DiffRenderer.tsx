"use client";

// ── Diff renderer ─────────────────────────────────────────────────────────────

interface DiffLine {
  key: string;
  type: "hunk" | "added" | "removed" | "context";
  oldNum: number | null;
  newNum: number | null;
  content: string;
}

export function DiffRenderer({ patch }: { patch: string }) {
  if (!patch) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-muted-foreground py-8">
        No diff available for this file.
      </div>
    );
  }

  const lines = patch.split("\n");
  let oldLine = 0;
  let newLine = 0;

  const rendered: DiffLine[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("\\")) continue; // no-newline markers

    if (line.startsWith("@@")) {
      // Parse hunk header: @@ -oldStart,oldCount +newStart,newCount @@
      const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = parseInt(match[1], 10) - 1;
        newLine = parseInt(match[2], 10) - 1;
      }
      rendered.push({ key: `hunk-${i}`, type: "hunk", oldNum: null, newNum: null, content: line });
    } else if (line.startsWith("+") && !line.startsWith("+++")) {
      newLine++;
      rendered.push({ key: `add-${i}`, type: "added", oldNum: null, newNum: newLine, content: line.slice(1) });
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      oldLine++;
      rendered.push({ key: `del-${i}`, type: "removed", oldNum: oldLine, newNum: null, content: line.slice(1) });
    } else if (line.startsWith(" ") || (!line.startsWith("+++") && !line.startsWith("---"))) {
      if (line.startsWith("+++") || line.startsWith("---")) continue;
      oldLine++;
      newLine++;
      rendered.push({ key: `ctx-${i}`, type: "context", oldNum: oldLine, newNum: newLine, content: line.startsWith(" ") ? line.slice(1) : line });
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono leading-5 border-collapse">
        <tbody>
          {rendered.map((dl) => {
            if (dl.type === "hunk") {
              return (
                <tr key={dl.key} className="bg-blue-500/10">
                  <td className="w-10 px-1 text-right text-blue-300/60 select-none border-r border-border" />
                  <td className="w-10 px-1 text-right text-blue-300/60 select-none border-r border-border" />
                  <td className="w-4 px-1 text-blue-300/60 select-none" />
                  <td className="px-2 text-blue-300/80 whitespace-pre">{dl.content}</td>
                </tr>
              );
            }
            if (dl.type === "added") {
              return (
                <tr key={dl.key} className="bg-green-500/10 hover:bg-green-500/15">
                  <td className="w-10 px-1 text-right text-muted-foreground/40 select-none border-r border-border" />
                  <td className="w-10 px-1 text-right text-green-400/70 select-none border-r border-border">{dl.newNum}</td>
                  <td className="w-4 px-1 text-green-400 font-bold select-none">+</td>
                  <td className="px-2 text-green-300 whitespace-pre">{dl.content}</td>
                </tr>
              );
            }
            if (dl.type === "removed") {
              return (
                <tr key={dl.key} className="bg-red-500/10 hover:bg-red-500/15">
                  <td className="w-10 px-1 text-right text-red-400/70 select-none border-r border-border">{dl.oldNum}</td>
                  <td className="w-10 px-1 text-right text-muted-foreground/40 select-none border-r border-border" />
                  <td className="w-4 px-1 text-red-400 font-bold select-none">-</td>
                  <td className="px-2 text-red-300 whitespace-pre">{dl.content}</td>
                </tr>
              );
            }
            // context
            return (
              <tr key={dl.key} className="hover:bg-accent/10">
                <td className="w-10 px-1 text-right text-muted-foreground/40 select-none border-r border-border">{dl.oldNum}</td>
                <td className="w-10 px-1 text-right text-muted-foreground/40 select-none border-r border-border">{dl.newNum}</td>
                <td className="w-4 px-1 text-muted-foreground/30 select-none"> </td>
                <td className="px-2 text-foreground/80 whitespace-pre">{dl.content}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
