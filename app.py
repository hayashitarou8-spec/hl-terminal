import json, time, threading, urllib.request, csv, io, datetime as dt
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
HL = "https://api.hyperliquid.xyz/info"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
import hmac, os
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
_tok = (os.environ.get("ACCESS_TOKEN") or "").strip()
_tok_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".access_token")
if not _tok and os.path.isfile(_tok_file):
    _tok = open(_tok_file).read().strip()
if len(_tok) < 16:
    raise RuntimeError("ACCESS_TOKEN env (or .access_token) required, >=16 chars")
TOKEN = _tok

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.middleware("http")
async def gate(request: Request, call_next):
    if request.url.path in ("/healthz", "/icon.png", "/manifest.webmanifest"):
        return await call_next(request)
    q = request.query_params.get("t"); c = request.cookies.get("hl_t")
    ok = (q and hmac.compare_digest(q, TOKEN)) or (c and hmac.compare_digest(c, TOKEN))
    if not ok:
        return HTMLResponse("<h1>401</h1><p>アクセストークンが必要です。</p>", status_code=401)
    if q:
        resp = RedirectResponse(request.url.path, status_code=303) if request.url.path == "/" else await call_next(request)
        resp.set_cookie("hl_t", TOKEN, httponly=True, secure=request.headers.get("x-forwarded-proto") == "https", samesite="lax", max_age=30*86400)
        return resp
    return await call_next(request)
_cache = {}; _lock = threading.Lock()
def cached(key, ttl, fn):
    with _lock:
        v = _cache.get(key)
        if v and time.time() - v[0] < ttl: return v[1]
    try: val = fn()
    except Exception as e:
        if v: return v[1]
        val = {"error": str(e)}
    with _lock: _cache[key] = (time.time(), val)
    return val
def get(url, ua=True):
    hdr = {"User-Agent": "curl/8.5.0" if "fred" in url else "Mozilla/5.0"}
    r = urllib.request.Request(url, headers=hdr)
    return urllib.request.urlopen(r, timeout=40).read()
def post(b):
    for i in range(4):
        try:
            r = urllib.request.Request(HL, json.dumps(b).encode(), {"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(r, timeout=20))
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    raise err
def now_iso(): return dt.datetime.now(dt.timezone.utc).isoformat()

def ctxs():
    def f():
        rows = []
        for dex in (None, "xyz"):
            b = {"type": "metaAndAssetCtxs"}
            if dex: b["dex"] = dex
            m, c = post(b)
            for a, x in zip(m["universe"], c):
                if a.get("isDelisted") or not x.get("markPx"): continue
                mk = float(x["markPx"]); pv = float(x.get("prevDayPx") or 0)
                fr = float(x["funding"])
                rows.append(dict(src=dex or "main", sym=a["name"], mark=mk, chg=(mk/pv-1)*100 if pv else None,
                    fund=fr*100, ann=fr*24*365*100, prem=float(x.get("premium") or 0)*100,
                    oi=float(x["openInterest"])*mk, vol=float(x["dayNtlVlm"]), maxLev=a.get("maxLeverage")))
        return {"ts": now_iso(), "rows": rows}
    return cached("ctx", 45, f)

def ema_series(v, n):
    k = 2/(n+1); e = v[0]; out = []
    for x in v: e = x*k + e*(1-k); out.append(e)
    return out
def rsi(c, n=14):
    if len(c) <= n: return None
    g = l = 0
    for i in range(1, n+1):
        d = c[i]-c[i-1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n+1, len(c)):
        d = c[i]-c[i-1]; g = (g*(n-1)+max(d, 0))/n; l = (l*(n-1)+max(-d, 0))/n
    return 100 if l == 0 else 100-100/(1+g/l)
def atr(k, n=14):
    tr = [max(k[i]['h']-k[i]['l'], abs(k[i]['h']-k[i-1]['c']), abs(k[i]['l']-k[i-1]['c'])) for i in range(1, len(k))]
    a = sum(tr[:n])/n
    for t in tr[n:]: a = (a*(n-1)+t)/n
    return a
def candles(sym, iv, days, ttl=300):
    def f():
        now = int(time.time()*1000)
        K = post({"type": "candleSnapshot", "req": {"coin": sym, "interval": iv, "startTime": now-days*86400000, "endTime": now}})
        return [{"t": x["t"]//1000, **{k: float(x[k]) for k in "ohlcv"}} for x in K]
    return cached(f"c:{sym}:{iv}", ttl, f)

def analyze(r):
    s = r["sym"]
    a = candles(s, "1h", 7); time.sleep(0.4); b = candles(s, "4h", 30)
    if isinstance(a, dict) or isinstance(b, dict) or len(b) < 30: return None
    c4 = [x['c'] for x in b]; c1 = [x['c'] for x in a]; m = r["mark"]
    e20 = ema_series(c4, 20)[-1]; e50 = ema_series(c4, 50)[-1]
    r1, r4 = rsi(c1), rsi(c4); A = atr(b); ap = A/m*100
    H7 = max(x['h'] for x in a); L7 = min(x['l'] for x in a); H30 = max(x['h'] for x in b); L30 = min(x['l'] for x in b)
    trend = "上昇" if m > e20 > e50 else "下降" if m < e20 < e50 else "レンジ"
    # transparent rules
    tag, side, conf, why = "様子見", None, 0.3, []
    if m >= H7*0.995 and trend == "上昇": tag, side, conf = "ブレイク", "long", 0.45; why.append("7日高値圏＋上昇トレンド")
    elif r4 is not None and r4 < 25 and r["ann"] < -30: tag, side, conf = "踏み上げ候補", "long", 0.4; why.append("4h RSI<25 かつ資金調達 年率<-30%")
    elif r1 is not None and r1 < 25 and m <= L7*1.01: tag, side, conf = "売られすぎ反発", "long", 0.4; why.append("1h RSI<25 かつ7日安値付近")
    elif trend == "下降" and (r1 or 50) < 60: tag, side, conf = "戻り売り", "short", 0.45; why.append("4h EMA20<EMA50 の下")
    elif trend == "上昇" and (r1 or 50) > 40: tag, side, conf = "押し目買い", "long", 0.45; why.append("4h EMA20>EMA50 の上")
    if side == "short" and r["ann"] > 10: conf += 0.05; why.append("資金調達プラス（ロング過密）")
    if side == "long" and r["ann"] < -10: conf += 0.05; why.append("資金調達マイナス（ショート過密）")
    if side == "short" and (r1 or 50) < 30: conf -= 0.05; why.append("1h RSI<30 追撃不利")
    if ap > 6: conf -= 0.05; why.append("ATR大")
    plan = None
    if side == "short":
        ez = (max(m, e20) , max(m, e20)+0.3*A); stop = ez[1]+1.2*A; tgt = min(L7, ez[0]-2*A)
        plan = dict(entry=ez, stop=stop, target=tgt)
    elif side == "long":
        ez = ((min(m, e20)-0.3*A) if tag == "押し目買い" else m-0.2*A, min(m, e20) if tag == "押し目買い" else m+0.1*A)
        stop = min(ez[0]-1.2*A, L7*0.995 if tag != "ブレイク" else ez[0]-1.5*A); tgt = max(ez[1]+2*A, e20 if e20 > ez[1] else 0)
        plan = dict(entry=ez, stop=stop, target=tgt)
    if plan:
        mid = sum(plan["entry"])/2; risk = abs(mid-plan["stop"]); plan["rr"] = abs(plan["target"]-mid)/risk if risk else None
        if plan["rr"] and plan["rr"] < 1.2: conf -= 0.05; why.append("RR<1.2")
    return dict(r, e20=e20, e50=e50, r1=r1, r4=r4, atr=ap, H7=H7, L7=L7, H30=H30, L30=L30,
                dH7=(m/H7-1)*100, dL7=(m/L7-1)*100, dH30=(m/H30-1)*100, dL30=(m/L30-1)*100,
                trend=trend, tag=tag, side=side, conf=round(max(conf, 0.1), 2), why=why, plan=plan)

def universe():
    rows = ctxs().get("rows", [])
    mn = sorted([r for r in rows if r["src"] == "main"], key=lambda r: -r["vol"])[:25]
    xy = sorted([r for r in rows if r["src"] == "xyz"], key=lambda r: -r["vol"])[:10]
    return mn + xy

@app.get("/api/overview")
def overview():
    d = ctxs(); rows = d.get("rows", [])
    key = {r["sym"]: r for r in rows if r["src"] == "main" and r["sym"] in ("BTC", "ETH", "HYPE")}
    def br(src):
        rs = [r for r in rows if r["src"] == src and r["chg"] is not None and r["vol"] > 0]
        return dict(up=sum(r["chg"] > 0 for r in rs), down=sum(r["chg"] < 0 for r in rs), n=len(rs),
                    avgAnn=sum(r["ann"] for r in rs)/len(rs) if rs else None,
                    vol=sum(r["vol"] for r in rs), oi=sum(r["oi"] for r in rs))
    return {"ts": d.get("ts"), "key": key, "breadth": {"main": br("main"), "xyz": br("xyz")}, "error": d.get("error")}

@app.get("/api/setups")
def setups():
    return _setups()
def _setups(fresh=False):
    def f():
        out = []
        for r in universe():
            try:
                x = analyze(r)
                if x: out.append(x)
            except Exception: pass
            time.sleep(0.3)
        return {"ts": now_iso(), "rows": out}
    if fresh: return f()
    with _lock: v = _cache.get("setups")
    return v[1] if v else {"ts": None, "rows": [], "pending": True}

@app.get("/api/candles/{sym}")
def cndl(sym: str, iv: str = "4h"):
    k = candles(sym, iv, 30 if iv == "4h" else 7)
    if isinstance(k, dict): return k
    cl = [x["c"] for x in k]
    return {"k": k, "e20": ema_series(cl, 20), "e50": ema_series(cl, 50)}

@app.get("/api/flows")
def flows():
    d = ctxs(); rows = d.get("rows", [])
    pf = cached("pf", 60, lambda: post({"type": "predictedFundings"}))
    venues = {}
    if isinstance(pf, list):
        for coin, vs in pf:
            m = {}
            for v, info in vs:
                if info and info.get("fundingRate") is not None:
                    h = info.get("fundingIntervalHours") or 1
                    m[v] = float(info["fundingRate"])/h*24*365*100
            venues[coin] = m
    top = sorted([r for r in rows if r["vol"] > 0], key=lambda r: -r["oi"])[:60]
    for r in top:
        r = r
        v = venues.get(r["sym"], {}) if r["src"] == "main" else {}
        r["bin"] = v.get("BinPerp"); r["byb"] = v.get("BybitPerp"); r["hlPred"] = v.get("HlPerp")
        flags = []
        if abs(r["ann"]) > 50: flags.append("資金調達 極端")
        if r["oi"] < 2e6 and abs(r["ann"]) > 30: flags.append("小OI×偏り")
        if abs(r["prem"]) > 0.3: flags.append("プレミアム乖離")
        r["flags"] = flags
    return {"ts": d.get("ts"), "rows": top, "pfOk": isinstance(pf, list)}

FRED = {"DGS10": "米10年債利回り", "DGS2": "米2年債利回り", "DTWEXBGS": "ドル指数(FRB広義)", "FEDFUNDS": "FF金利(実効・月次)", "CPIAUCSL": "CPI(指数)"}
def fred(i):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={i}").decode()
    pts = [(row[0], float(row[1])) for row in list(csv.reader(io.StringIO(txt)))[1:] if len(row) > 1 and row[1] not in ("", ".")]
    return pts
@app.get("/api/macro")
def macro():
    def f():
        out = {}
        for i, name in FRED.items():
            try:
                p = fred(i)
                if i == "CPIAUCSL":
                    yoy = [(p[j][0], (p[j][1]/p[j-12][1]-1)*100) for j in range(12, len(p))]
                    out[i] = dict(name="CPI 前年比(%)", date=yoy[-1][0], value=yoy[-1][1], spark=[v for _, v in yoy[-24:]], src="FRED CPIAUCSL")
                else:
                    n = 24 if i == "FEDFUNDS" else 60
                    out[i] = dict(name=name, date=p[-1][0], value=p[-1][1], spark=[v for _, v in p[-n:]], src=f"FRED {i}")
            except Exception as e: out[i] = dict(name=FRED[i], error="データ取得不可")
        try:
            j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=3mo&interval=1d"))["chart"]["result"][0]
            cl = [c for c in j["indicators"]["quote"][0]["close"] if c is not None]
            out["DXY"] = dict(name="DXY(ICE)", date=dt.datetime.fromtimestamp(j["meta"]["regularMarketTime"], dt.timezone.utc).strftime("%Y-%m-%d"), value=j["meta"]["regularMarketPrice"], spark=cl[-60:], src="Yahoo DX-Y.NYB")
        except Exception: out["DXY"] = dict(name="DXY(ICE)", error="データ取得不可")
        if "DGS10" in out and "DGS2" in out and "value" in out["DGS10"] and "value" in out["DGS2"]:
            out["SPREAD"] = dict(name="10年-2年 スプレッド(%)", date=out["DGS10"]["date"], value=out["DGS10"]["value"]-out["DGS2"]["value"], spark=[], src="FRED 計算")
        return {"ts": now_iso(), "series": out, "fomc": "2026-10-27〜28"}
    return cached("macro", 1800, f)

@app.get("/api/fundamentals")
def fundamentals():
    def f():
        rows = ctxs().get("rows", []); out = {"ts": now_iso()}
        for src in ("main", "xyz"):
            rs = [r for r in rows if r["src"] == src]
            out[src] = dict(n=len(rs), vol=sum(r["vol"] for r in rs), oi=sum(r["oi"] for r in rs))
        out["xyzList"] = sorted([dict(sym=r["sym"], mark=r["mark"], chg=r["chg"], vol=r["vol"], oi=r["oi"], ann=r["ann"], maxLev=r["maxLev"]) for r in rows if r["src"] == "xyz" and r["vol"] > 0], key=lambda r: -r["vol"])
        h = next((r for r in rows if r["sym"] == "HYPE" and r["src"] == "main"), None); out["hype"] = h
        try:
            fe = json.loads(get("https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyFees&excludeTotalDataChartBreakdown=true"))
            out["fees"] = dict(d24=fe.get("total24h"), d7=fe.get("total7d"), d30=fe.get("total30d"), spark=[v for _, v in (fe.get("totalDataChart") or [])[-60:]])
        except Exception: out["fees"] = {"error": "データ取得不可"}
        try:
            fe = json.loads(get("https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyRevenue&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"))
            out["rev"] = dict(d24=fe.get("total24h"), d30=fe.get("total30d"))
        except Exception: out["rev"] = {"error": "データ取得不可"}
        try: out["tvl"] = float(get("https://api.llama.fi/tvl/hyperliquid"))
        except Exception: out["tvl"] = None
        return out
    return cached("fund", 600, f)

import extra as X
@app.get("/api/geo")
def api_geo(): return cached("geo", 900, X.geo)
@app.get("/api/cryptonews")
def api_cn(): return cached("cnews", 900, lambda: X.news(X.CRYPTO_FEEDS))
@app.get("/api/calendar")
def api_cal(): return cached("cal", 1800, X.calendar)
@app.get("/api/econ")
def api_econ(): return cached("econ", 1800, X.econ)
ETF_TTL = 2400  # 40分
def _etf_refresh():
    try:
        d = X.etf_all()
        with _lock:
            old = (_cache.get("etf") or (0, None))[1]
            if old:  # 個別失敗時は直前の成功値を残す（stale 表示）
                for k, v in d["assets"].items():
                    o = old["assets"].get(k)
                    if not v.get("ok") and o and o.get("ok"): d["assets"][k] = dict(o, stale=True)
            _cache["etf"] = (time.time(), d)
    except Exception: pass
def _etf_loop():
    while True:
        _etf_refresh()
        with _lock: v = _cache.get("etf")
        bad = not v or any(not a.get("ok") or a.get("stale") for a in v[1]["assets"].values())
        time.sleep(300 if bad else ETF_TTL)  # 失敗があれば5分後に再試行
@app.get("/api/etf")
def api_etf():
    with _lock: v = _cache.get("etf")
    return v[1] if v else {"ts": None, "pending": True, "assets": {}}
def _etf_btc_rows():
    b = api_etf().get("assets", {}).get("BTC") or {}
    if not b.get("ok"): return {"error": "データ取得不可"}
    return {"ts": api_etf().get("ts"), "rows": [{"date": r["date"], "total": r["total"]} for r in b["hist"]], "src": "Farside Investors (US$m)"}
@app.get("/api/sentiment")
def api_sent():
    def f():
        out = {"ts": now_iso()}
        try: out["fng"] = X.fng()
        except Exception: out["fng"] = {"error": "データ取得不可"}
        return out
    return dict(cached("sent", 1200, f), etf=_etf_btc_rows())
@app.get("/api/ticker")
def api_ticker():
    rows = ctxs().get("rows", []); want = ["BTC", "ETH", "HYPE", "SOL", "xyz:SP500", "xyz:GOLD", "xyz:NVDA", "xyz:SILVER"]
    m = {r["sym"]: r for r in rows}
    return {"ts": ctxs().get("ts"), "items": [dict(sym=s.replace("xyz:", ""), mark=m[s]["mark"], chg=m[s]["chg"]) for s in want if s in m]}
@app.get("/icon.png")
def icon(): return FileResponse(__file__.rsplit("/", 1)[0] + "/static/icon.png", media_type="image/png")
@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({"name": "HL Terminal", "short_name": "HL Terminal", "start_url": "/", "display": "standalone",
        "background_color": "#05070d", "theme_color": "#05070d", "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}]})
import kosatsu as K
_last_regen = 0.0
_k = {"key": None, "val": None}; _klock = threading.Lock()
@app.get("/api/kosatsu")
def api_kosatsu(regen: bool = False):
    sc = setups()
    if sc.get("pending") or not sc.get("rows"): return {"pending": True}
    global _last_regen
    if regen:
        if time.time() - _last_regen < 60: regen = False
        else: _last_regen = time.time()
    with _klock:
        if not regen and _k["key"] == sc["ts"] and _k["val"]: return _k["val"]
        F = K.facts(sc, overview(), flows(), macro(), fundamentals())
        try: F["geo"] = [dict(title=x["title"], src=x["src"], ts=x["ts"], tags=[t["tag"] for t in x["tags"]]) for x in api_geo().get("items", []) if x["tags"]][:4]
        except Exception: F["geo"] = []
        try:
            sn = api_sent(); F["fng"] = {k: sn["fng"].get(k) for k in ("value", "label", "date")} if "value" in sn.get("fng", {}) else None
        except Exception: F["fng"] = None
        try: F["etf"] = {k: {x: v.get(x) for x in ("date", "latest", "sum5", "days5", "streak")} for k, v in api_etf().get("assets", {}).items() if v.get("ok") and k in ("BTC", "ETH")}
        except Exception: F["etf"] = {}
        mode, model, err = "rule", None, None
        try:
            text, model = K.grok_text(F); mode = "grok"
        except Exception as e:
            err = str(e); text = K.rule_text(F)
        val = {"pending": False, "scan_ts": sc["ts"], "gen_ts": now_iso(), "mode": mode, "model": model, "fallback_reason": err if mode == "rule" else None, "text": text, "summary": K.summary(F)}
        _k.update(key=sc["ts"], val=val)
        return val

@app.get("/")
def index(): return FileResponse(__file__.rsplit("/", 1)[0] + "/static/index.html")

def _warm():
    while True:
        try:
            r = _setups(fresh=True)
            if r.get("rows"):
                with _lock: _cache["setups"] = (time.time(), r)
            macro(); fundamentals(); api_geo(); api_cn(); api_cal(); api_econ(); api_sent()
        except Exception: pass
        time.sleep(90)
@app.on_event("startup")
def _start():
    threading.Thread(target=_etf_loop, daemon=True).start()
    threading.Thread(target=_warm, daemon=True).start()
