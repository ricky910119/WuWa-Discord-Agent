#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 遊戲情報機器人(官方第一手來源版)
- 來源只用官方管道:官網/官方 API、Steam 官方公告、官方 YouTube 頻道(不使用新聞媒體)
- 每則消息「分開發送」,內容直接附上原始網址,讓 Discord 自動產生縮圖預覽。
遊戲設定放在同目錄的 config.json;Webhook 從環境變數 WEBHOOK 讀取 (GitHub Secret)。
"""
import os, sys, json, html, time, datetime as dt
import requests, feedparser

DAYS_BACK = int(os.getenv("DAYS_BACK", "7"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "10"))
POST_DELAY = float(os.getenv("POST_DELAY", "1.2"))   # 每則間隔(避免被限流)
HTTP_TIMEOUT = 25
UA = "Mozilla/5.0 (compatible; DiscordGameNewsBot/1.0)"
TW = dt.timezone(dt.timedelta(hours=8))   # 台北 / 官方常用 UTC+8
MINDATE = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _to_utc(st):
    if not st:
        return None
    try:
        return dt.datetime(*st[:6], tzinfo=dt.timezone.utc)
    except Exception:
        return None


def fetch_rss(url, label="", prefix=""):
    """通用 RSS/Atom(含 YouTube)抓取。"""
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for e in feedparser.parse(r.content).entries:
            title = html.unescape((e.get("title") or "").strip())
            link = e.get("link") or ""
            pub = _to_utc(e.get("published_parsed")) or _to_utc(e.get("updated_parsed"))
            if title and link:
                items.append({"title": prefix + title, "link": link,
                              "published": pub, "source": label})
    except Exception as ex:
        print(f"  [warn] RSS 失敗 {url[:60]}: {ex}", file=sys.stderr)
    return items


def fetch_steam(appid, label="Steam"):
    """Steam 官方新聞 API。"""
    items = []
    url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
           f"?appid={appid}&count=20&maxlength=0&format=json")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for n in r.json().get("appnews", {}).get("newsitems", []):
            items.append({
                "title": (n.get("title") or "").strip(),
                "link": n.get("url") or "",
                "published": dt.datetime.fromtimestamp(n.get("date", 0), tz=dt.timezone.utc),
                "source": label,
            })
    except Exception as ex:
        print(f"  [warn] Steam 失敗 appid={appid}: {ex}", file=sys.stderr)
    return items


def fetch_kuro(url, base_link, label="官網"):
    """Kuro Games 官方網站新聞 API (鳴潮)。createTime 視為 UTC+8。"""
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": UA},
                         params={"t": int(time.time() * 1000)}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for a in r.json().get("article", []):
            aid = a.get("articleId")
            title = (a.get("articleTitle") or "").strip()
            ct = a.get("createTime") or ""
            pub = None
            try:
                pub = dt.datetime.strptime(ct, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TW).astimezone(dt.timezone.utc)
            except Exception:
                pass
            if aid and title:
                items.append({"title": title, "link": base_link.format(id=aid),
                              "published": pub, "source": label})
    except Exception as ex:
        print(f"  [warn] Kuro 失敗 {url[:60]}: {ex}", file=sys.stderr)
    return items


def collect(game):
    raw = []
    for f in game["feeds"]:
        t = f.get("type")
        if t == "rss":
            raw += fetch_rss(f["url"], f.get("label", ""))
        elif t == "youtube":
            raw += fetch_rss(f["url"], f.get("label", "YouTube"), prefix="🎬 ")
        elif t == "steam":
            raw += fetch_steam(f["appid"], f.get("label", "Steam"))
        elif t == "kuro":
            raw += fetch_kuro(f["url"], f["base"], f.get("label", "官網"))

    # 去重(以連結為主)
    seen, dedup = set(), []
    for it in raw:
        k = (it["link"] or "").strip() or "".join(it["title"].lower().split())[:40]
        if k and k not in seen:
            seen.add(k); dedup.append(it)

    key = lambda it: it["published"] or MINDATE
    cutoff = _now_utc() - dt.timedelta(days=DAYS_BACK)
    recent = [it for it in dedup if it["published"] and it["published"] >= cutoff]
    recent.sort(key=key, reverse=True)

    fb = False
    if not recent:
        dedup.sort(key=key, reverse=True)
        recent = dedup[:3]; fb = True
    return recent[:MAX_ITEMS], fb


def item_content(it):
    """一則訊息:標題 + 日期/來源,下一行放原始網址(讓 Discord 產生縮圖)。"""
    meta = []
    if it["published"]:
        meta.append(it["published"].astimezone(TW).strftime("%Y/%m/%d"))
    if it["source"]:
        meta.append(it["source"])
    tail = f"　`{' · '.join(meta)}`" if meta else ""
    return f"**{it['title']}**{tail}\n{it['link']}"


def post_message(webhook, content):
    for _ in range(4):
        r = requests.post(webhook, json={"content": content},
                         headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5); continue
        print(f"  [error] Discord {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return False
    return False


def main():
    with open(os.path.join(os.path.dirname(__file__), "config.json"), encoding="utf-8") as fp:
        game = json.load(fp)
    webhook = os.getenv("WEBHOOK", "").strip()
    if not webhook:
        print("[error] 找不到環境變數 WEBHOOK", file=sys.stderr); sys.exit(1)

    items, fb = collect(game)
    print(f"{game['name']}:取得 {len(items)} 則{'(退回近期)' if fb else ''}")

    today = _now_utc().astimezone(TW).strftime("%Y/%m/%d")
    header = f"{game['emoji']} **{game['name']}｜官方情報 {today}**" + ("(近期)" if fb else "")
    post_message(webhook, header)

    if not items:
        post_message(webhook, "本週暫無官方新消息。")
        print("無項目,已發送提示。"); return

    # 由舊到新逐則發送,讓最新的消息落在頻道最下方(最新位置)
    sent = 0
    for it in sorted(items, key=lambda x: x["published"] or MINDATE):
        time.sleep(POST_DELAY)
        if post_message(webhook, item_content(it)):
            sent += 1
    print(f"發送完成:{sent}/{len(items)} 則 ✅")
    if sent == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
