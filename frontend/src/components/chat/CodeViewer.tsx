"use client";

import { useMemo } from "react";
import hljs from "highlight.js/lib/core";
import langPython from "highlight.js/lib/languages/python";
import langJS from "highlight.js/lib/languages/javascript";
import langTS from "highlight.js/lib/languages/typescript";
import langBash from "highlight.js/lib/languages/bash";
import langJSON from "highlight.js/lib/languages/json";
import langYAML from "highlight.js/lib/languages/yaml";
import langCSS from "highlight.js/lib/languages/css";
import langXML from "highlight.js/lib/languages/xml";
import langGo from "highlight.js/lib/languages/go";
import langRust from "highlight.js/lib/languages/rust";
import langJava from "highlight.js/lib/languages/java";
import langSQL from "highlight.js/lib/languages/sql";
import langMarkdown from "highlight.js/lib/languages/markdown";
import { getLanguage } from "@/lib/language-detection";

hljs.registerLanguage("python", langPython);
hljs.registerLanguage("javascript", langJS);
hljs.registerLanguage("typescript", langTS);
hljs.registerLanguage("bash", langBash);
hljs.registerLanguage("shell", langBash);
hljs.registerLanguage("json", langJSON);
hljs.registerLanguage("yaml", langYAML);
hljs.registerLanguage("css", langCSS);
hljs.registerLanguage("html", langXML);
hljs.registerLanguage("xml", langXML);
hljs.registerLanguage("go", langGo);
hljs.registerLanguage("rust", langRust);
hljs.registerLanguage("java", langJava);
hljs.registerLanguage("sql", langSQL);
hljs.registerLanguage("markdown", langMarkdown);

export function CodeViewer({ content, filename }: { content: string; filename: string }) {
  const lang = getLanguage(filename);
  const highlighted = useMemo(() => {
    if (!content || lang === "plaintext" || lang === "markdown") return "";
    try {
      if (hljs.getLanguage(lang)) {
        return hljs.highlight(content, { language: lang, ignoreIllegals: true }).value;
      }
      return hljs.highlightAuto(content).value;
    } catch {
      return "";
    }
  }, [content, lang]);

  return (
    <pre className="hljs m-0 rounded-none h-full p-4 text-xs leading-5 overflow-auto">
      {highlighted
        ? <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        : <code>{content}</code>
      }
    </pre>
  );
}
