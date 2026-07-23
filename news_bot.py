#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 遊戲情報機器人(官方第一手來源 · 每小時檢查 · 只發新的)
- 來源只用官方管道:官網/官方 API、Steam 官方公告、官方 YouTube 頻道(不使用新聞媒體)
- 每次執行:抓官方最近更新,和「已發送記錄 state/sent.json」比對,只發沒發過的新項目。
- 每則消息分開發送,內容直接附原始網址,讓 Discord 自動產生縮圖預覽。
遊戲設定放在同目錄 config.json;Webhook 從環境變數 WEBHOOK 讀取 (GitHub Secret)。
"""
import os, sys, json, html, time, datetime as dt
import requests, feedparser

DAYS_BACK = int(os.getenv("DAYS_BACK", "2"))       # 每次往回看幾天(有記憶,窗口小即可)
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "12"))      # 單次最多發幾則(防爆量)
POST_DELAY = float(os.getenv("POST_DELAY", "1.2"))
KEEP_DAYS = int(os.getenv("KEEP_DAYS", "60"))      # 記錄保留天數
HTTP_TIMEOUT = 25
UA = "Mozilla/5.0 (compatible; DiscordGameNewsBot/1.0)"
TW = dt.timezone(dt.timedelta(hours=8))
MINDATE = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state", "sent.json")


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

    seen, dedup = set(), []
    for it in raw:
        k = (it["link"] or "").strip()
        if k and k not in seen:
            seen.add(k); dedup.append(it)

    cutoff = _now_utc() - dt.timedelta(days=DAYS_BACK)
    recent = [it for it in dedup if it["published"] and it["published"] >= cutoff]
    recent.sort(key=lambda it: it["published"] or MINDATE)   # 由舊到新
    return recent


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fp:
            return json.load(fp)          # { link: "ISO 送出時間" }
    except Exception:
        return {}


def save_state(state):
    cutoff = _now_utc() - dt.timedelta(days=KEEP_DAYS)
    pruned = {}
    for link, iso in state.items():
        try:
            if dt.datetime.fromisoformat(iso) >= cutoff:
                pruned[link] = iso
        except Exception:
            pruned[link] = iso
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fp:
        json.dump(pruned, fp, ensure_ascii=False, indent=0)


def item_content(it):
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
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fp:
        game = json.load(fp)
    webhook = os.getenv("WEBHOOK", "").strip()
    if not webhook:
        print("[error] 找不到環境變數 WEBHOOK", file=sys.stderr); sys.exit(1)

    state = load_state()
    recent = collect(game)
    new_items = [it for it in recent if it["link"] not in state][:MAX_ITEMS]
    print(f"{game['name']}:近 {DAYS_BACK} 天 {len(recent)} 則,其中新項目 {len(new_items)} 則")

    if not new_items:
        print("沒有新項目,這次不發送。")
        return

    sent = 0
    now_iso = _now_utc().isoformat()
    for it in new_items:
        time.sleep(POST_DELAY)
        if post_message(webhook, item_content(it)):
            state[it["link"]] = now_iso
            sent += 1
    save_state(state)
    print(f"發送完成:{sent}/{len(new_items)} 則 ✅")
    if sent == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
