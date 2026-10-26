import os, json, time, urllib.request, datetime as dt
JST = dt.timezone(dt.timedelta(hours=9))
def f(v, d=2): return "-" if v is None else (f"{v:,.{d}f}" if abs(v) >= 1 else f"{v:.{max(d,4)}g}")
def px(v): return "-" if v is None else (f"{v:,.1f}" if v >= 1000 else f"{v:,.2f}" if v >= 10 else f"{v:.4g}")
def sg(v, d=1): return "-" if v is None else f"{v:+.{d}f}%"

def facts(scan, ov, flows, macro, fund):
    rows = scan["rows"]
    S = macro.get("series", {})
    m = lambda k: (S.get(k) or {}).get("value")
    plans = [r for r in rows if r.get("plan") and r["plan"].get("rr") and r["plan"]["rr"] >= 1.5]
    top = sorted(plans, key=lambda r: (-r["conf"], -r["plan"]["rr"], -r["vol"]))[:5]
    avoid = []
    for r in flows.get("rows", []):
        if r["flags"]: avoid.append(dict(sym=r["sym"], why=r["flags"], ann=r["ann"], oi=r["oi"]))
    for r in rows:
        if r["atr"] > 6: avoid.append(dict(sym=r["sym"], why=[f"ATR {r['atr']:.1f}%と値幅過大"], ann=r["ann"], oi=r["oi"]))
        elif r.get("side") == "short" and r["r1"] is not None and r["r1"] < 30: avoid.append(dict(sym=r["sym"], why=[f"1h RSI {r['r1']:.0f}で売られすぎ、追撃ショート不利"], ann=r["ann"], oi=r["oi"]))
    seen = set(); av = []
    for a in avoid:
        if a["sym"] not in seen and a["sym"] not in {t["sym"] for t in top}: seen.add(a["sym"]); av.append(a)
    tr = {"上昇": 0, "下降": 0, "レンジ": 0}
    for r in rows: tr[r["trend"]] += 1
    return dict(scan_ts=scan["ts"], breadth=ov["breadth"], key=ov["key"], trend_count=tr,
        btc=next((r for r in rows if r["sym"] == "BTC"), None), eth=next((r for r in rows if r["sym"] == "ETH"), None),
        macro=dict(us10y=m("DGS10"), us10y_date=(S.get("DGS10") or {}).get("date"), us2y=m("DGS2"), dxy=m("DXY"), dxy_spark=(S.get("DXY") or {}).get("spark", [])[-6:], ff=m("FEDFUNDS"), cpi_yoy=m("CPIAUCSL"), cpi_date=(S.get("CPIAUCSL") or {}).get("date"), fomc=macro.get("fomc")),
        fund=dict(fees24=(fund.get("fees") or {}).get("d24"), tvl=fund.get("tvl")), top=top, avoid=av[:5])

def reason(r):
    p = r["plan"]; s = []
    s.append(f"価格{px(r['mark'])}は4h EMA20({px(r['e20'])})・EMA50({px(r['e50'])})に対して{r['trend']}トレンド、1h RSI {f(r['r1'],1)}・4h RSI {f(r['r4'],1)}。")
    s.append(f"7日高値比{sg(r['dH7'])}・7日安値比{sg(r['dL7'])}、ATR(4h) {r['atr']:.2f}%、資金調達は年率{sg(r['ann'])}。")
    if r["why"]: s.append("判定根拠: " + "／".join(r["why"]) + "。")
    return "".join(s)

def rule_text(F):
    b = F["breadth"]; mc = F["macro"]; L = []
    now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    L.append(f"## 今日のセットアップ考察（{now}・ルール生成）")
    L.append("### 相場概況")
    mn, xy = b["main"], b["xyz"]
    tc = F["trend_count"]
    L.append(f"クリプト・パーペは{mn['n']}銘柄中 上昇{mn['up']}／下落{mn['down']}、HIP-3株パーペは{xy['n']}銘柄中 上昇{xy['up']}／下落{xy['down']}。"
             f"スキャン対象{sum(tc.values())}銘柄の4hトレンドは 上昇{tc['上昇']}・下降{tc['下降']}・レンジ{tc['レンジ']}で、"
             + ("下向き優勢。戻り売り目線が基本。" if tc["下降"] > tc["上昇"] * 2 else "上向き優勢。押し目買い目線が基本。" if tc["上昇"] > tc["下降"] * 2 else "方向感は混在。"))
    for k in ("btc", "eth"):
        r = F[k]
        if r: L.append(f"{r['sym']}は{px(r['mark'])}（24h {sg(r['chg'],2)}）、4h{r['trend']}（EMA20 {px(r['e20'])}／EMA50 {px(r['e50'])}）、1h RSI {f(r['r1'],1)}、資金調達 年率{sg(r['ann'])}、OI ${r['oi']/1e9:.2f}B。")
    L.append(f"資金調達の平均はクリプト年率{sg(mn['avgAnn'])}、株パーペ年率{sg(xy['avgAnn'])}。")
    mm = []
    if mc["us10y"] is not None: mm.append(f"米10年債{mc['us10y']:.2f}%（{mc['us10y_date']}）")
    if mc["us2y"] is not None: mm.append(f"2年債{mc['us2y']:.2f}%")
    if mc["dxy"] is not None:
        sp = mc["dxy_spark"]; d = "上昇基調" if sp and sp[-1] > sp[0] else "低下基調" if sp else ""
        mm.append(f"DXY {mc['dxy']:.2f}（直近{d}）")
    if mc["cpi_yoy"] is not None: mm.append(f"CPI前年比{mc['cpi_yoy']:.2f}%（{mc['cpi_date']}分）")
    if mc["ff"] is not None: mm.append(f"FF金利{mc['ff']:.2f}%")
    L.append("マクロ: " + ("、".join(mm) if mm else "データ取得不可") + f"。次回FOMCは{mc['fomc']}で、それまでは金利・ドル高がリスク資産の重しになりやすい。")
    et = etf_line(F)
    if et: L.append(et)
    if F.get("fng"): L.append(f"センチメント: Fear & Greed {F['fng']['value']}（{F['fng']['label']}、{F['fng']['date']}）。")
    if F.get("geo"):
        L.append("地政学・ヘッドライン（見出しベース、内容未検証）:")
        for g in F["geo"]: L.append(f"- [{'/'.join(g['tags'])}] {g['title']}（{g['src']}）")
    L.append("### 注目セットアップ")
    if not F["top"]: L.append("RR1.5以上の候補なし。様子見。")
    for i, r in enumerate(F["top"], 1):
        p = r["plan"]; side = "ロング" if r["side"] == "long" else "ショート"
        L.append(f"**{i}. {r['sym']} {side}（{r['tag']}）** 確信度{r['conf']:.2f}\n- エントリー {px(p['entry'][0])}〜{px(p['entry'][1])}／損切り {px(p['stop'])}／利確 {px(p['target'])}／RR {p['rr']:.2f}\n- {reason(r)}")
    L.append("### 避けたい銘柄")
    if not F["avoid"]: L.append("特になし。")
    for a in F["avoid"]: L.append(f"- {a['sym']}: {'・'.join(a['why'])}（資金調達 年率{sg(a['ann'])}、OI ${a['oi']/1e6:.1f}M）")
    L.append("※ 分析用・投資助言ではない。数値はHyperliquid/FRED/Yahoo/DefiLlama/Farsideの取得値。")
    return "\n".join(L)

def etf_line(F):
    E = F.get("etf") or {}; parts = []
    for k in ("BTC", "ETH"):
        e = E.get(k)
        if not e or e.get("latest") is None: continue
        d = "流入" if e["latest"] > 0 else "流出" if e["latest"] < 0 else "ゼロ"
        p = f"{k} {e['latest']:+,.1f}（{d}・{e['date']}）、直近{e['days5']}日計{e['sum5']:+,.1f}"
        if abs(e.get("streak") or 0) >= 3: p += f"、{abs(e['streak'])}日連続{'流入' if e['streak'] > 0 else '流出'}"
        parts.append(p)
    return ("現物ETFフロー（米国・US$m・Farside）: " + "／".join(parts) + "。") if parts else None

def grok_text(F):
    key = os.environ.get("XAI_API_KEY")
    if not key: raise RuntimeError("no key")
    sys = ("あなたは数値を一切変えない編集者でもある。Hyperliquidのトレード分析者。与えられたJSONの数値だけを使い、数値を作らないこと。日本語Markdownで『今日のセットアップ考察』を書く。"
           "構成: ### 相場概況（ブレッドス、BTC/ETHの状態、資金調達・偏り、米10年債/DXY/CPI/次回FOMC）→ ### 注目セットアップ（topの各銘柄: 方向、エントリー帯、損切り、利確、RR、確信度をJSONの値どおりに、理由2-3文で実数を引用）→ ### 避けたい銘柄（avoidと理由）。最後に『分析用・投資助言ではない』。見出し以外の前置き不要。")
    base = rule_text(F)
    body = "以下は検証済みの数値入りの下書き。数値・単位・表記はこの下書きのものを一字一句そのまま使い、新しい数値を計算・作成しないこと。文章を読みやすく深く書き直す（各セットアップの理由は2-3文）。\n\n" + base
    last = None
    for model in ("grok-4-fast-non-reasoning", "grok-4", "grok-3-mini"):
        try:
            req = urllib.request.Request("https://api.x.ai/v1/chat/completions", json.dumps({"model": model, "temperature": 0.3,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": body}]}).encode(),
                {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            j = json.load(urllib.request.urlopen(req, timeout=90))
            t = j["choices"][0]["message"]["content"].strip()
            import re
            allowed = set(re.findall(r"\d[\d,]*\.?\d*", base))
            bad = [n for n in re.findall(r"\d[\d,]*\.?\d*", t) if len(n.replace(",", "").replace(".", "")) >= 3 and n not in allowed]
            if bad: raise RuntimeError("unverified numbers: " + ",".join(bad[:5]))
            now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
            return f"## 今日のセットアップ考察（{now}・Grok生成）\n" + t, model
        except Exception as e: last = e
    raise RuntimeError(f"grok failed: {type(last).__name__}")


def summary(F):
    b = F["breadth"]["main"]; tc = F["trend_count"]; out = []
    reg = "下向き優勢" if tc["下降"] > tc["上昇"] * 2 else "上向き優勢" if tc["上昇"] > tc["下降"] * 2 else "方向感混在"
    s = f"地合い{reg}：4h 下降{tc['下降']}・上昇{tc['上昇']}・レンジ{tc['レンジ']}、24hはクリプト上昇{b['up']}/{b['n']}"
    if F.get("fng"): s += f"、Fear&Greed {F['fng']['value']}"
    out.append(s)
    if F["top"]:
        r = F["top"][0]; p = r["plan"]
        out.append(f"最有力：{r['sym']} {'ロング' if r['side']=='long' else 'ショート'}（{r['tag']}）RR {p['rr']:.2f}・確信度{r['conf']:.2f}")
    else: out.append("RR1.5以上の候補なし。様子見。")
    w = []
    if F.get("geo"):
        tags = []
        for g in F["geo"]:
            for t in g["tags"]:
                if t not in tags: tags.append(t)
        w.append("地政学ヘッドライン(" + "/".join(tags[:3]) + ")")
    E = F.get("etf") or {}
    ef = [f"{k} {E[k]['sum5']:+,.0f}M" for k in ("BTC", "ETH") if E.get(k) and E[k].get("sum5") is not None]
    if ef: s2 = "ETF5日計 " + " / ".join(ef); out[0] += "、" + s2
    if F["avoid"]: w.append("回避: " + "・".join(a["sym"].replace("xyz:", "") for a in F["avoid"][:3]))
    w.append(f"次回FOMC {F['macro']['fomc']}")
    out.append("注意：" + "／".join(w))
    return out
