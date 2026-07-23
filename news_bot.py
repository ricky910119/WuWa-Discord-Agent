#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 遊戲情報機器人 —— 鳴潮 Wuthering Waves
每週抓取最新消息,整理成中文重點條列 + 官方連結,發到 Discord 頻道 (Webhook)。
Webhook 從環境變數 WEBHOOK 讀取 (GitHub Secret),不寫死在程式裡。
"""
import os, sys, html, time, datetime as dt
from urllib.parse import quote
import requests, feedparser

DAYS_BACK = int(os.getenv("DAYS_BACK", "7"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "8"))
HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; DiscordGameNewsBot/1.0)"


def google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


GAME = {
    "name": "鳴潮 Wuthering Waves",
    "emoji": "🌊",
    "color": 0x8E7CFF,
    "feeds": [
        {"type": "rss", "url": google_news_rss('"鳴潮" OR "Wuthering Waves"')},
    ],
}


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _to_utc(st):
    if not st:
        return None
    try:
        return dt.datetime(*st[:6], tzinfo=dt.timezone.utc)
    except Exception:
        return None


def fetch_rss(url):
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for e in feedparser.parse(r.content).entries:
            title = html.unescape((e.get("title") or "").strip())
            link = e.get("link") or ""
            pub = _to_utc(e.get("published_parsed")) or _to_utc(e.get("updated_parsed"))
            source = ""
            if e.get("source") and isinstance(e.source, dict):
                source = e.source.get("title", "")
            if not source and " - " in title:
                title, source = title.rsplit(" - ", 1)
            if title and link:
                items.append({"title": title, "link": link, "published": pub, "source": source})
    except Exception as ex:
        print(f"  [warn] RSS 失敗 {url[:60]}: {ex}", file=sys.stderr)
    return items


def fetch_steam(appid):
    items = []
    url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
           f"?appid={appid}&count=15&maxlength=0&format=json")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for n in r.json().get("appnews", {}).get("newsitems", []):
            items.append({
                "title": (n.get("title") or "").strip(),
                "link": n.get("url") or "",
                "published": dt.datetime.fromtimestamp(n.get("date", 0), tz=dt.timezone.utc),
                "source": n.get("feedlabel") or "Steam",
            })
    except Exception as ex:
        print(f"  [warn] Steam 失敗 appid={appid}: {ex}", file=sys.stderr)
    return items


def collect():
    raw = []
    for f in GAME["feeds"]:
        raw += fetch_rss(f["url"]) if f["type"] == "rss" else fetch_steam(f["appid"])
    seen, dedup = set(), []
    for it in raw:
        k = "".join(it["title"].lower().split())[:40]
        if k and k not in seen:
            seen.add(k); dedup.append(it)
    cutoff = _now_utc() - dt.timedelta(days=DAYS_BACK)
    recent = [it for it in dedup if it["published"] and it["published"] >= cutoff]
    key = lambda it: it["published"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    recent.sort(key=key, reverse=True)
    fb = False
    if not recent:
        dedup.sort(key=key, reverse=True)
        recent = dedup[:3]; fb = True
    return recent[:MAX_ITEMS], fb


def build_embed(items, fb):
    today = _now_utc().astimezone(dt.timezone(dt.timedelta(hours=8)))
    if not items:
        desc = "本週暫無擷取到的新消息。"
    else:
        lines = []
        for it in items:
            t = it["title"].strip()
            if len(t) > 140:
                t = t[:139] + "…"
            meta = []
            if it["published"]:
                meta.append(it["published"].astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%m/%d"))
            if it["source"]:
                meta.append(it["source"])
            m = f"　`{' · '.join(meta)}`" if meta else ""
            lines.append(f"• [{t}]({it['link']}){m}")
        desc = "\n".join(lines)
        if len(desc) > 4000:
            desc = desc[:3990] + "\n…"
    header = f"{GAME['emoji']} {GAME['name']}｜本週情報 {today.strftime('%Y/%m/%d')}"
    if fb:
        header += "(近期)"
    return {"title": header, "description": desc, "color": GAME["color"],
            "footer": {"text": "自動彙整 · 由 GitHub Actions 每週發送"}}


def post(webhook, embed):
    for _ in range(4):
        r = requests.post(webhook, json={"embeds": [embed]}, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5); continue
        print(f"  [error] Discord {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return False
    return False


def main():
    webhook = os.getenv("WEBHOOK", "").strip()
    if not webhook:
        print("[error] 找不到環境變數 WEBHOOK", file=sys.stderr); sys.exit(1)
    items, fb = collect()
    print(f"{GAME['name']}:取得 {len(items)} 則{'(退回近期)' if fb else ''}")
    if post(webhook, build_embed(items, fb)):
        print("發送成功 ✅")
    else:
        print("發送失敗 ❌", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
