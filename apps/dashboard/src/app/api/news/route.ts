import { NextResponse } from "next/server";

import { gatewayBase } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Local headlines for the login page (UI_REVAMP_v2 Feature B, revised): BBC
 * Tamil RSS — free, no API key, no geolocation. Fetched and parsed server-side.
 * Feed source precedence: admin-configured URL (Administration → Settings →
 * `generalSettings.newsFeedUrl`, read via the public news-config endpoint) →
 * `NEWS_RSS_URL` env → BBC Tamil. Always returns `{articles: []}` on any
 * failure so the widget can hide silently.
 */
const DEFAULT_FEED = "https://feeds.bbci.co.uk/tamil/rss.xml";
const MAX_ARTICLES = 4;

async function configuredFeedUrl(): Promise<string | null> {
  try {
    const resp = await fetch(`${gatewayBase()}/api/v1/public/news-config`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(3000),
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const url = typeof data.newsFeedUrl === "string" ? data.newsFeedUrl.trim() : "";
    return url.startsWith("http") ? url : null;
  } catch {
    return null;
  }
}

type Article = { title: string; url: string; publishedAt: string | null; source: string };

function textBetween(block: string, tag: string): string | null {
  const m = block.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  if (!m) return null;
  // Strip CDATA wrappers and collapse whitespace.
  return m[1].replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/\s+/g, " ").trim() || null;
}

export async function GET() {
  const feedUrl = (await configuredFeedUrl()) || process.env.NEWS_RSS_URL || DEFAULT_FEED;
  try {
    const resp = await fetch(feedUrl, {
      next: { revalidate: 1800 },
      headers: { "User-Agent": "UniServe-dashboard/1.0 (+rss reader)" },
      signal: AbortSignal.timeout(8000),
    });
    if (!resp.ok) return NextResponse.json({ articles: [] });
    const xml = await resp.text();

    const channelTitle = textBetween(xml.split(/<item[\s>]/i)[0] ?? "", "title") || "BBC Tamil";
    const articles: Article[] = [];
    for (const m of xml.matchAll(/<item[\s>]([\s\S]*?)<\/item>/gi)) {
      const block = m[1];
      const title = textBetween(block, "title");
      const url = textBetween(block, "link");
      if (!title || !url) continue;
      articles.push({ title, url, publishedAt: textBetween(block, "pubDate"), source: channelTitle });
      if (articles.length >= MAX_ARTICLES) break;
    }
    return NextResponse.json({ articles });
  } catch {
    return NextResponse.json({ articles: [] });
  }
}
