import { useEffect, useState } from "react";
import type { HighlighterGeneric } from "shiki";
import Button from "../ui/Button";
import { usePersistentState } from "../lib/usePersistentState";

type Highlighter = HighlighterGeneric<"python" | "xml", "github-dark" | "github-light">;

// Module-level singleton — one highlighter instance shared across every
// mount of this tab (diagram code + drawio XML both use it), not
// re-initialized per tab switch. Narrow bundle (2 langs, 2 themes) so this
// stays a small dynamic import rather than landing in the initial chunk
// (plan §G: shiki via a narrow, lazily-imported bundle). Only the TYPE
// import above is eager — `import type` is erased at build time, so it
// carries no runtime bundle cost.
let highlighterPromise: Promise<Highlighter> | null = null;
function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import("shiki").then(({ createHighlighter }) =>
      createHighlighter({ themes: ["github-dark", "github-light"], langs: ["python", "xml"] }),
    );
  }
  return highlighterPromise;
}

const isBoolean = (v: unknown): v is boolean => typeof v === "boolean";

/** Code tab (drawio XML) / diagram source tab — replaces the bare
 * `<pre>{code}</pre>` (plan §G) with shiki highlighting, a Wrap toggle
 * (persisted), and a Copy button. */
export default function CodeTab({ code, lang, title }: { code: string; lang: "python" | "xml"; title: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [wrap, setWrap] = usePersistentState("da.ui.codeWrap", false, isBoolean);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getHighlighter()
      .then((hl) => {
        if (cancelled) return;
        setHtml(hl.codeToHtml(code, { lang, themes: { light: "github-light", dark: "github-dark" }, defaultColor: false }));
      })
      .catch(() => {
        if (!cancelled) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-raised px-4 py-2">
        <span className="text-xs font-medium text-secondary">{title}</span>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" aria-pressed={wrap} onClick={() => setWrap((w) => !w)}>
            {wrap ? "No wrap" : "Wrap"}
          </Button>
          <Button variant="ghost" size="sm" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
      <div
        className={`flex-1 overflow-auto bg-app text-code [&_pre]:!bg-transparent [&_pre]:p-6 ${
          wrap ? "[&_pre]:whitespace-pre-wrap [&_pre]:break-words" : ""
        }`}
      >
        {html ? (
          // eslint-disable-next-line react/no-danger -- shiki's own sanitized output, no user input
          <div dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <pre className="p-6 font-mono text-code text-secondary">{code}</pre>
        )}
      </div>
    </div>
  );
}
