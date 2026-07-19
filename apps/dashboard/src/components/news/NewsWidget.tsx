"use client";

import { useEffect, useState } from "react";
import { Globe } from "lucide-react";

type Article = { title: string; url: string; publishedAt: string | null; source: string };

/**
 * Login-page headlines (UI_REVAMP_v2 Feature B, revised): BBC Tamil RSS via the
 * server-side `/api/news` route — no API key, no geolocation. Graceful
 * degradation: any error or an empty feed hides the widget entirely.
 */
export default function NewsWidget() {
  const [state, setState] = useState<"loading" | "ready" | "hidden">("loading");
  const [articles, setArticles] = useState<Article[]>([]);

  useEffect(() => {
    fetch("/api/news")
      .then((r) => r.json())
      .then((d) => {
        const list: Article[] = Array.isArray(d.articles) ? d.articles : [];
        if (list.length === 0) {
          setState("hidden");
        } else {
          setArticles(list);
          setState("ready");
        }
      })
      .catch(() => setState("hidden"));
  }, []);

  if (state === "hidden") return null;

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-white/70">
        <Globe className="h-3.5 w-3.5" /> Local Headlines
      </p>
      {state === "loading" ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-white/10" />
          ))}
        </div>
      ) : (
        <ul className="space-y-2">
          {articles.map((a) => (
            <li key={a.url}>
              <a
                href={a.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block rounded-lg bg-white/10 px-3 py-2 transition-colors hover:bg-white/20"
              >
                <p className="text-[10px] uppercase tracking-wide text-white/60">
                  {a.source}
                  {a.publishedAt ? ` · ${a.publishedAt}` : ""}
                </p>
                <p className="line-clamp-2 text-sm text-white">{a.title}</p>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
