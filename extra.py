import re, json, time, csv, io, html, urllib.request, datetime as dt, email.utils
import xml.etree.ElementTree as ET
JST = dt.timezone(dt.timedelta(hours=9))
def get(url, ua="Mozilla/5.0 (Macintosh) HLTerminal/2.0", timeout=25):
    r = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    return urllib.request.urlopen(r, timeout=timeout).read()
def iso(): return dt.datetime.now(dt.timezone.utc).isoformat()

GEO_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Google News (EN) 地政学・原油", "https://news.google.com/rss/search?q=geopolitics+oil+Middle+East+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News (EN) 米中・関税", "https://news.google.com/rss/search?q=tariffs+China+trade+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News (EN) ロシア・ウクライナ", "https://news.google.com/rss/search?q=Russia+Ukraine+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News (JA) 地政学", "https://news.google.com/rss/search?q=%E5%9C%B0%E6%94%BF%E5%AD%A6+OR+%E5%8E%9F%E6%B2%B9+OR+%E9%96%A2%E7%A8%8E+when:2d&hl=ja&gl=JP&ceid=JP:ja"),
]
CRYPTO_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]
TAGS = [  # tag, regex, impact hint
    ("原油", r"oil|crude|opec|brent|wti|原油|石油|pipeline|パイプライン", "原油↑リスク・インフレ懸念→株/BTCに重し、金銀は支え"),
    ("中東", r"iran|israel|gaza|saudi|houthi|yemen|lebanon|syria|middle east|red sea|hormuz|イラン|イスラエル|ガザ|サウジ|中東|フーシ", "原油・金↑、リスクオフで株/BTC↓になりやすい"),
    ("米中", r"china|beijing|xi jinping|taiwan|中国|台湾|米中|習近平", "半導体株(NVDA/MU/SK系)・ハイテク株に変動、BTCは間接"),
    ("関税", r"tariff|trade war|duties|関税|貿易", "株(輸出・ハイテク)↓、ドル高→BTCに重し"),
    ("戦争", r"\bwars?\b|missile|\bstrikes?\b|\battack(s|ed|ing)?\b|invasion|troops|drones?\b|ukraine|russia|戦争|攻撃|ミサイル|侵攻|ウクライナ|ロシア", "リスクオフ：株/BTC↓、金銀・原油↑"),
    ("制裁", r"sanction|embargo|export control|制裁|禁輸|輸出規制", "対象国関連の商品・半導体に影響、原油供給懸念"),
    ("金融政策", r"\bfed\b|fomc|powell|rate cut|rate hike|inflation|cpi|利下げ|利上げ|日銀|frb|インフレ", "金利↓なら株/BTC↑、金利↑なら逆"),
]
def tag(title):
    t = title.lower(); out = []
    for name, rx, hint in TAGS:
        if re.search(rx, t): out.append({"tag": name, "hint": hint})
    return out
def parse_rss(src, url, n=12):
    root = ET.fromstring(get(url))
    items = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        pd = it.findtext("pubDate")
        try: ts = email.utils.parsedate_to_datetime(pd).astimezone(dt.timezone.utc).isoformat()
        except Exception: ts = None
        srcname = it.findtext("source") or src
        if it.findtext("source") and title.endswith(" - " + srcname): title = title[: -len(" - " + srcname)]
        if title and len(title) >= 15: items.append({"title": title, "link": link, "ts": ts, "src": srcname, "feed": src, "tags": tag(title)})
        if len(items) >= n: break
    return items
def news(feeds):
    out, status = [], []
    for name, url in feeds:
        try:
            it = parse_rss(name, url); out += it; status.append({"src": name, "ok": True, "n": len(it)})
        except Exception as e: status.append({"src": name, "ok": False, "err": type(e).__name__})
    seen = set(); uniq = []
    for x in sorted(out, key=lambda x: x["ts"] or "", reverse=True):
        k = re.sub(r"\W", "", x["title"].lower())[:60]
        if k not in seen: seen.add(k); uniq.append(x)
    return {"ts": iso(), "items": uniq, "status": status}
def geo():
    d = news(GEO_FEEDS)
    tagged = [x for x in d["items"] if x["tags"]]
    cnt = {}
    for x in tagged:
        for t in x["tags"]: cnt[t["tag"]] = cnt.get(t["tag"], 0) + 1
    d["counts"] = dict(sorted(cnt.items(), key=lambda kv: -kv[1]))
    d["items"] = (tagged + [x for x in d["items"] if not x["tags"]])[:40]
    return d

def calendar():
    j = json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    out = []
    for e in j:
        if e.get("country") != "USD" and e.get("impact") != "High": continue
        try: t = dt.datetime.fromisoformat(e["date"]).astimezone(JST)
        except Exception: continue
        out.append(dict(title=e["title"], country=e["country"], jst=t.strftime("%m/%d") + "(" + "月火水木金土日"[t.weekday()] + ") " + t.strftime("%H:%M"), iso=t.isoformat(),
                        impact=e.get("impact"), forecast=e.get("forecast") or None, previous=e.get("previous") or None, actual=e.get("actual") or None))
    return {"ts": iso(), "src": "ForexFactory (faireconomy.media) 今週", "items": out,
            "fixed": [{"title": "FOMC 政策金利発表", "jst": "10/29(木) 03:00", "note": "2026-10-27〜28 開催（FRB公表日程）", "impact": "High"}]}

FRED_X = [  # id, name, mode, unit
    ("CPIAUCSL", "CPI 前年比", "yoy", "%"), ("PCEPILFE", "コアPCE 前年比", "yoy", "%"), ("UNRATE", "失業率", "lvl", "%"),
    ("PAYEMS", "非農業部門雇用者数 前月差", "diff", "千人"), ("GDPC1", "実質GDP 前期比年率", "qoq", "%"),
    ("T10Y2Y", "10年-2年 スプレッド", "lvl", "%"), ("VIXCLS", "VIX 恐怖指数", "lvl", ""), ("DCOILWTICO", "WTI原油", "lvl", "$")]
def fred(i):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={i}", ua="curl/8.5.0").decode()
    return [(r[0], float(r[1])) for r in list(csv.reader(io.StringIO(txt)))[1:] if len(r) > 1 and r[1] not in ("", ".")]
def econ():
    out = []
    for i, name, mode, unit in FRED_X:
        try:
            p = fred(i)
            if mode == "yoy": s = [(p[j][0], (p[j][1]/p[j-12][1]-1)*100) for j in range(12, len(p))]
            elif mode == "diff": s = [(p[j][0], p[j][1]-p[j-1][1]) for j in range(1, len(p))]
            elif mode == "qoq": s = [(p[j][0], ((p[j][1]/p[j-1][1])**4-1)*100) for j in range(1, len(p))]
            else: s = p
            n = 90 if i in ("VIXCLS", "DCOILWTICO", "T10Y2Y") else 24
            s = s[-n:]
            out.append(dict(id=i, name=name, unit=unit, date=s[-1][0], value=s[-1][1], prev=s[-2][1] if len(s) > 1 else None, spark=[v for _, v in s], src=f"FRED {i}"))
        except Exception: out.append(dict(id=i, name=name, error="データ取得不可"))
        time.sleep(0.2)
    for sym, name in (("GC=F", "金 先物"), ("SI=F", "銀 先物")):
        try:
            r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"))["chart"]["result"][0]
            cl = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
            out.append(dict(id=sym, name=name, unit="$", date=dt.datetime.fromtimestamp(r["meta"]["regularMarketTime"], JST).strftime("%Y-%m-%d"),
                            value=r["meta"]["regularMarketPrice"], prev=cl[-2] if len(cl) > 1 else None, spark=cl[-60:], src=f"Yahoo {sym}"))
        except Exception: out.append(dict(id=sym, name=name, error="データ取得不可"))
    return {"ts": iso(), "items": out}

def fng():
    j = json.loads(get("https://api.alternative.me/fng/?limit=30"))["data"]
    return {"ts": iso(), "value": int(j[0]["value"]), "label": j[0]["value_classification"],
            "date": dt.datetime.fromtimestamp(int(j[0]["timestamp"]), JST).strftime("%Y-%m-%d"),
            "spark": [int(x["value"]) for x in reversed(j)], "src": "alternative.me"}
def etf():
    s = get("https://farside.co.uk/bitcoin-etf-flow-all-data/").decode("utf-8", "ignore")
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", s, re.S):
        c = [html.unescape(re.sub("<[^>]+>", "", x)).strip() for x in re.findall(r"<td.*?</td>", tr, re.S)]
        if len(c) > 3 and re.match(r"\d{1,2} \w{3} \d{4}", c[0]):
            v = c[-1].replace(",", "")
            if v in ("", "-"): continue
            neg = v.startswith("("); v = v.strip("()")
            try: rows.append({"date": c[0], "total": (-1 if neg else 1)*float(v)})
            except ValueError: pass
    if not rows: raise RuntimeError("parse")
    rows = rows[-15:]
    return {"ts": iso(), "rows": rows, "src": "Farside Investors (US$m)"}
