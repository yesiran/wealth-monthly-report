#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月报工作台公共库：东财数据接口、基金身份拟合、日期工具。
所有网络函数支持 cache_dir 缓存（原始响应落盘，供离线回归测试复用）。"""
import json, logging, os, re, time, urllib.request, urllib.parse
from datetime import date, datetime

WORKBENCH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_logger(name):
    """双通道日志：控制台(INFO) + 按日期落盘(DEBUG, logs/YYYYMMDD/<name>_HHMMSS.log)。
    同名 logger 复用，避免重复 handler。"""
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S"))
    lg.addHandler(sh)
    day_dir = os.path.join(WORKBENCH_ROOT, "logs", datetime.now().strftime("%Y%m%d"))
    os.makedirs(day_dir, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(day_dir, f"{name}_{datetime.now().strftime('%H%M%S')}.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    lg.addHandler(fh)
    return lg


# 市场代码映射：泛化的股票定价通道。us 等未列入的市场=暂不支持定价，S2 会自动移入"未纳入"
STOCK_MARKETS = {
    "hk": {"em_prefix": "116", "ccy": "HKD"},
    "sh": {"em_prefix": "1", "ccy": "CNY"},
    "sz": {"em_prefix": "0", "ccy": "CNY"},
}


def norm_position(p):
    """持仓类型归一化 -> (kind, market, ccy)。兼容旧 schema 的 hk_stock/cn_fund。"""
    t = p.get("type", "")
    if t == "hk_stock":
        return "stock", "hk", "HKD"
    if t == "stock":
        mk = p.get("market", "")
        meta = STOCK_MARKETS.get(mk)
        return "stock", mk, (meta["ccy"] if meta else None)
    if t in ("cn_fund", "fund"):
        return "fund", None, "CNY"
    return t or "other", None, None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"


def http_get(url, referer=None, cache_dir=None, cache_key=None, retries=3):
    """GET 带重试；若 cache_dir 下已有 cache_key 文件则直接读缓存。"""
    if cache_dir and cache_key:
        fp = os.path.join(cache_dir, cache_key)
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                return f.read()
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    if referer:
        req.add_header("Referer", referer)
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                text = r.read().decode("utf-8", "ignore")
            if cache_dir and cache_key:
                os.makedirs(cache_dir, exist_ok=True)
                with open(os.path.join(cache_dir, cache_key), "w", encoding="utf-8") as f:
                    f.write(text)
            return text
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"http_get failed after {retries} tries: {url}: {last}")


# ---------------- 解析器（纯函数，离线可测） ----------------

def parse_fund_search(text):
    """fundsuggest 响应 -> [(code, name)]"""
    j = json.loads(text)
    return [(d["CODE"], d["NAME"]) for d in j.get("Datas", []) if re.match(r"^\d{6}$", d.get("CODE", ""))]


def parse_fund_nav(text):
    """lsjz 响应 -> [(date, nav_float, pct_str, fhsp_str)] 新在前"""
    j = json.loads(text)
    out = []
    for row in j["Data"]["LSJZList"]:
        try:
            out.append((row["FSRQ"], float(row["DWJZ"]), row.get("JZZZL", ""), row.get("FHSP", "") or ""))
        except (ValueError, TypeError):
            continue
    return out


def parse_kline(text):
    """push2his kline -> [{date, open, close, high, low}] 旧在前"""
    j = json.loads(text)
    d = j.get("data") or {}
    out = []
    for k in d.get("klines") or []:
        f = k.split(",")
        out.append({"date": f[0], "open": float(f[1]), "close": float(f[2]),
                    "high": float(f[3]), "low": float(f[4])})
    return out


# ---------------- 数据接口 ----------------

def fund_search(key, cache_dir=None):
    url = ("https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key="
           + urllib.parse.quote(key))
    return parse_fund_search(http_get(url, cache_dir=cache_dir, cache_key=f"search_{key}.json"))


def fund_nav(code, min_rows=80, max_pages=8, cache_dir=None):
    """净值历史：按需翻页直到 min_rows 行（接口单页上限会漂移，不做假设）。"""
    out = []
    for p in range(1, max_pages + 1):
        url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={p}&pageSize=49"
        text = http_get(url, referer=f"https://fundf10.eastmoney.com/jjjz_{code}.html",
                        cache_dir=cache_dir, cache_key=f"nav_{code}_p{p}.json")
        rows = parse_fund_nav(text)
        if not rows:
            break
        out.extend(rows)
        if len(out) >= min_rows:
            break
        time.sleep(0.3)
    return out


def fund_fullname(code, cache_dir=None):
    """基金全称与跟踪标的（基本概况页）"""
    text = http_get(f"https://fundf10.eastmoney.com/jbgk_{code}.html",
                    cache_dir=cache_dir, cache_key=f"jbgk_{code}.html")
    m = re.search(r"基金全称</th><td[^>]*>([^<]+)", text)
    m2 = re.search(r"跟踪标的</t[hd]><td[^>]*>([^<]+)", text)
    return (m.group(1) if m else "", m2.group(1) if m2 else "")


def _kline_em(secid, beg, end, fqt=0, cache_dir=None):
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&klt=101&fqt={fqt}&beg={beg}&end={end}"
           f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&ut={EM_UT}")
    key = f"kline_{secid.replace('.', '_')}_{fqt}_{beg}_{end}.json"
    return parse_kline(http_get(url, cache_dir=cache_dir, cache_key=key))


def _secid_to_tencent(secid):
    mkt, code = secid.split(".")
    if mkt == "116":
        return "hk" + code
    if mkt == "1":
        return "sh" + code
    if mkt == "0":
        return "sz" + code
    if secid == "100.HSI":
        return "hkHSI"
    if secid == "124.HSTECH":
        return "hkHSTECH"
    return None  # 汇率等腾讯不支持


def parse_kline_tencent(text, tcode):
    """腾讯 fqkline 响应 -> (rows, corp_action_dates)。
    corp_action = 窗口内出现分红/派息标记（FHcontent/paixiri 非空；纯回购不算）。"""
    j = json.loads(text)
    d = j["data"][tcode]
    arr = d.get("day") or d.get("qfqday") or []
    rows, actions = [], []
    for it in arr:
        rows.append({"date": it[0], "open": float(it[1]), "close": float(it[2]),
                     "high": float(it[3]), "low": float(it[4])})
        if len(it) > 6 and isinstance(it[6], dict):
            if it[6].get("FHcontent") or it[6].get("paixiri"):
                actions.append(it[0])
    return rows, actions


def _kline_tencent(secid, beg, end, cache_dir=None):
    tcode = _secid_to_tencent(secid)
    if not tcode:
        raise RuntimeError(f"tencent 不支持 secid {secid}")
    b = f"{beg[:4]}-{beg[4:6]}-{beg[6:]}"
    e = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tcode},day,{b},{e},400,")
    key = f"tkline_{tcode}_{beg}_{end}.json"
    return parse_kline_tencent(http_get(url, cache_dir=cache_dir, cache_key=key), tcode)


def kline_full(secid, beg, end, fqt=0, cache_dir=None):
    """双源日K：东财优先，失败自动切腾讯。
    返回 {"rows": [...], "source": "em"|"tencent", "corp_actions": [dates]|None}
    corp_actions 仅腾讯源提供（东财源用 fqt=0/1 对比法另行检测）。"""
    try:
        return {"rows": _kline_em(secid, beg, end, fqt, cache_dir), "source": "em",
                "corp_actions": None}
    except Exception as e:
        rows, actions = _kline_tencent(secid, beg, end, cache_dir)
        print(f"  [lib] 东财失败({type(e).__name__})，已切换腾讯源: {secid}")
        return {"rows": rows, "source": "tencent", "corp_actions": actions}


def kline(secid, beg, end, fqt=0, cache_dir=None):
    return kline_full(secid, beg, end, fqt, cache_dir)["rows"]


def fx_series(secid, beg, end, cache_dir=None):
    """汇率日序列：东财中间价优先，失败切 frankfurter(ECB参考价，略有差异需标注)。
    返回 {"rows": [[date, px]...], "source": ...}"""
    try:
        rows = _kline_em(secid, beg, end, 0, cache_dir)
        return {"rows": [[x["date"], x["close"]] for x in rows], "source": "em"}
    except Exception:
        pair = {"120.HKDCNYC": ("HKD", "CNY")}.get(secid)
        if not pair:
            raise
        b = f"{beg[:4]}-{beg[4:6]}-{beg[6:]}"
        e = f"{end[:4]}-{end[4:6]}-{end[6:]}"
        url = f"https://api.frankfurter.dev/v1/{b}..{e}?base={pair[0]}&symbols={pair[1]}"
        j = json.loads(http_get(url, cache_dir=cache_dir, cache_key=f"fx_{pair[0]}{pair[1]}_{beg}_{end}.json"))
        rows = sorted([[d, v[pair[1]]] for d, v in j["rates"].items()])
        print(f"  [lib] 汇率已切换 frankfurter(ECB) 源，与中间价略有差异")
        return {"rows": rows, "source": "frankfurter"}


def fundlist_grep(tokens, cache_dir):
    """全量基金列表兜底检索：所有 token 均出现在名称中即命中 -> [(code,name)]"""
    fp = os.path.join(cache_dir, "fundcode_search.js")
    if not os.path.exists(fp):
        http_get("https://fund.eastmoney.com/js/fundcode_search.js",
                 cache_dir=cache_dir, cache_key="fundcode_search.js")
    with open(fp, encoding="utf-8") as f:
        raw = f.read()
    out = []
    for m in re.finditer(r'"(\d{6})","[^"]*","([^"]+)"', raw):
        code, name = m.group(1), m.group(2)
        if all(t in name for t in tokens):
            out.append((code, name))
    return out


# ---------------- 基金身份拟合（核心风控） ----------------

def fit_fund_identity(candidates, amount, pnl_yday, pnl_total, nav_getter, asof=None, tol=0.03):
    """用截图三元组(持仓金额/昨日收益/持仓收益)在候选基金中拟合真实身份。
    原理：截图时点 asof 显示的是最近净值日 d1 的数据，d0 为其前一净值日。
      份额 s = 持仓金额 / nav_d1（无舍入放大），
      校验 s*(nav_d1-nav_d0) ≈ 昨日收益（残差容差 tol，默认0.03元，
      覆盖显示舍入±0.005 + 少量份额误差；债基净值日变仅0.003时该方向不放大误差）。
    d1 的搜索范围：给定 asof 时为 (asof-12天, asof]（QDII 有 T+1 滞后故留宽），
    否则为最近 6 个净值日。
    返回 [(code, name, d1, shares, err_pnl)] 按误差升序。"""
    lo = None
    if asof:
        d = date.fromisoformat(asof)
        lo = (d.toordinal() - 12, d.toordinal())
    hits = []
    for code, name in candidates:
        try:
            nav = nav_getter(code)
        except Exception:
            continue
        nav_sorted = sorted(nav)  # 旧->新
        best = None
        for i in range(1, len(nav_sorted)):
            d1 = nav_sorted[i][0]
            if lo:
                o = date.fromisoformat(d1).toordinal()
                if not (lo[0] < o <= lo[1]):
                    continue
            elif i < len(nav_sorted) - 6:
                continue
            n0, n1 = nav_sorted[i - 1][1], nav_sorted[i][1]
            # 份额=金额/净值（无舍入放大），残差=推算昨日收益 vs 截图昨日收益
            shares = amount / n1
            err = abs(shares * (n1 - n0) - pnl_yday)
            if err < tol and (best is None or err < best[4]):
                best = (code, name, d1, round(shares, 2), round(err, 4))
        if best:
            hits.append(best)
    return sorted(hits, key=lambda x: x[4])


def infer_buy_date(nav_series, shares, cost_amt, tol_rel=0.004):
    """由成本净值匹配买入确认日：cost_nav = cost_amt/shares，在净值序列中找最接近的日期。"""
    cost_nav = cost_amt / shares
    cands = []
    for d, v, *_ in sorted(nav_series):
        rel = abs(v - cost_nav) / cost_nav
        if rel < tol_rel:
            cands.append((rel, d, v))
    cands.sort()
    return cands[0][1] if cands else None


# ---------------- 日期工具 ----------------

def period_bounds(series_dates, period):
    """period='2026-06' -> (上月最后交易日, 本月最后交易日)，由实际数据日期推断。"""
    y, m = map(int, period.split("-"))
    month_first = f"{y:04d}-{m:02d}-01"
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    next_first = f"{ny:04d}-{nm:02d}-01"
    ds = sorted(set(series_dates))
    prev = [d for d in ds if d < month_first]
    cur = [d for d in ds if month_first <= d < next_first]
    if not prev or not cur:
        raise ValueError(f"period_bounds: 数据不足以覆盖 {period}（prev={len(prev)} cur={len(cur)}）")
    return prev[-1], cur[-1]
