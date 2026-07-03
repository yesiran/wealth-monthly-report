#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 行情采集：读 <period>/01_holdings.json -> 写 <period>/02_market.json
- 股票：按 market(hk/sh/sz) 走对应行情通道；未支持市场打 UNSUPPORTED_MARKET flag（S2 会移入未纳入）
- 基金：净值历史；code 为 null 的用截图数字拟合身份；缺"昨日收益"时降级为名称匹配并打低置信 flag
- 基准指数 + 汇率；原始响应缓存到 <period>/raw/（离线回归测试复用）
用法: python3 s1_fetch_market.py <period_dir>
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import (fund_search, fund_nav, fund_fullname, kline, kline_full, fx_series,
                 fundlist_grep, fit_fund_identity, period_bounds, get_logger,
                 norm_position, STOCK_MARKETS)

log = get_logger("s1")

COMPANIES = ["易方达", "汇添富", "华夏", "南方", "嘉实", "广发", "富国", "招商", "博时",
             "天弘", "国泰", "鹏华", "华安", "工银", "建信", "中欧", "兴全", "万家", "银华"]


def name_tokens(disp):
    comp = next((c for c in COMPANIES if disp.startswith(c)), disp[:3])
    core = disp[len(comp):]
    for w in ["ETF", "联接", "发起式", "（QDII）", "(QDII)", "证券投资基金", "指数", "基金"]:
        core = core.replace(w, "")
    core = re.sub(r"[ABCEIYD]$", "", core).strip()
    return comp, core


def gen_candidates(disp, cache_dir):
    comp, core = name_tokens(disp)
    seen, cands = set(), []

    def add(pairs):
        for c, n in pairs:
            if c not in seen:
                seen.add(c)
                cands.append((c, n))

    for key in [disp, comp + core, core]:
        try:
            add(fund_search(key, cache_dir=cache_dir))
        except Exception as e:
            log.debug(f"搜索[{key}]失败: {e}")
    subs = {core[i:i + L] for L in (4, 3, 2) for i in range(len(core) - L + 1)}
    for sub in sorted(subs, key=len, reverse=True)[:12]:
        try:
            add(fundlist_grep([comp, sub], cache_dir))
        except Exception as e:
            log.debug(f"列表grep[{comp}+{sub}]失败: {e}")
        if len(cands) >= 40:
            break
    log.debug(f"候选基金 {disp}: {len(cands)} 个 -> {cands[:10]}")
    return cands[:40]


def main(period_dir):
    with open(os.path.join(period_dir, "01_holdings.json"), encoding="utf-8") as f:
        H = json.load(f)
    period = H["period"]
    log.info(f"===== S1 开始: period={period} asof={H.get('asof')} 持仓 {len(H['positions'])} 只 =====")
    raw = os.path.join(period_dir, "raw")
    os.makedirs(raw, exist_ok=True)
    y, m = map(int, period.split("-"))
    beg = f"{y - 1 if m <= 2 else y}{(m - 2 - 1) % 12 + 1:02d}01"
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = f"{ny}{nm:02d}07"
    log.debug(f"抓取窗口 {beg} - {end}")

    out = {"period": period, "funds": {}, "stocks": {}, "benchmarks": {}, "fx": {},
           "resolution": [], "flags": []}
    nav_cache = {}

    def get_nav(code):
        if code not in nav_cache:
            nav_cache[code] = fund_nav(code, cache_dir=raw)
            log.debug(f"净值 {code}: {len(nav_cache[code])} 行, 最新 {nav_cache[code][0] if nav_cache[code] else '空'}")
        return nav_cache[code]

    # ---- 基金 ----
    for p in H["positions"]:
        kind, _, _ = norm_position(p)
        if kind != "fund":
            continue
        disp, shot = p["name_display"], p["screenshot"]
        code = p.get("code")
        if shot.get("pnl_yday") is not None:
            cands = [(code, disp)] if code else gen_candidates(disp, raw)
            method = "given" if code else "fitted"
            hits = fit_fund_identity(cands, shot["amount"], shot["pnl_yday"],
                                     shot.get("pnl_total", 0), get_nav, asof=H.get("asof"))
        else:
            # 降级路径：截图无"昨日收益"，只能按名称匹配，无法数值验证
            hits = []
            method = "name_only"
            cands = [(code, disp)] if code else gen_candidates(disp, raw)
            if cands:
                c0, n0 = cands[0]
                try:
                    nav = get_nav(c0)
                    d1, v1 = sorted(nav)[-1][0], sorted(nav)[-1][1]
                    hits = [(c0, n0, d1, round(shot["amount"] / v1, 2), -1.0)]
                    out["flags"].append(f"LOW_CONFIDENCE_FUND: {disp} 截图缺昨日收益，仅名称匹配为 {c0}，请人工确认")
                except Exception as e:
                    log.debug(f"降级匹配失败 {disp}: {e}")
        if not hits:
            out["flags"].append(f"UNRESOLVED_FUND: {disp} — 拟合无命中，需人工确认代码")
            out["resolution"].append({"display": disp, "method": method, "ok": False})
            log.warning(f"基金未解析: {disp}")
            continue
        code, name, d1, shares, err = hits[0]
        try:
            fullname, track = fund_fullname(code, cache_dir=raw)
        except Exception:
            fullname, track = "", ""
        nav = get_nav(code)
        out["funds"][code] = {
            "display": disp, "em_name": name, "fullname": fullname, "track": track,
            "nav": sorted([[d, v] for d, v, *_ in nav]),
            "fhsp": sorted([[d, fh] for d, v, z, fh in nav if fh]),
        }
        out["resolution"].append({"display": disp, "method": method, "ok": True,
                                  "code": code, "snapshot_nav_date": d1,
                                  "shares_fit": shares, "fit_err": err, "n_hits": len(hits)})
        log.info(f"基金解析 [{method}] {disp} -> {code} 份额={shares} 误差={err} 跟踪={track or '无'}")
        if len(hits) > 1 and hits[1][4] < 1.0:
            out["flags"].append(f"AMBIGUOUS_FUND: {disp} 次优候选 {hits[1][0]} 误差也很小({hits[1][4]})，请复核")

    # ---- 股票（按市场通道） ----
    for p in H["positions"]:
        kind, market, _ = norm_position(p)
        if kind != "stock":
            continue
        code = p["code"]
        meta = STOCK_MARKETS.get(market)
        if not meta:
            out["flags"].append(f"UNSUPPORTED_MARKET: {p.get('name', code)} market={market} 暂不支持定价，将列入未纳入")
            log.warning(f"暂不支持的市场: {p.get('name')} ({market})")
            continue
        secid = f"{meta['em_prefix']}.{code}"
        time.sleep(0.8)
        kf = kline_full(secid, beg, end, fqt=0, cache_dir=raw)
        adj = {}
        if kf["source"] == "em":
            time.sleep(0.8)
            k1 = kline(secid, beg, end, fqt=1, cache_dir=raw)
            adj = {x["date"]: x["close"] for x in k1}
        out["stocks"][code] = {"name": p["name"], "market": market, "source": kf["source"],
                               "close": [[x["date"], x["close"]] for x in kf["rows"]],
                               "_adj": adj, "_corp_actions": kf["corp_actions"] or [],
                               "dividend_flag": False}
        log.info(f"股票行情 {p['name']} {code}({market}) 源={kf['source']} {len(kf['rows'])}天")

    # ---- 基准 + 汇率 ----
    for b in H.get("benchmarks", []):
        time.sleep(0.8)
        k = kline(b["secid"], beg, end, fqt=0, cache_dir=raw)
        out["benchmarks"][b["key"]] = {"name": b["name"],
                                       "close": [[x["date"], x["close"]] for x in k]}
        log.debug(f"基准 {b['name']}: {len(k)}天")
    fx = fx_series(H["fx_secid"], beg, end, cache_dir=raw)
    out["fx"]["close"] = fx["rows"]
    out["fx"]["source"] = fx["source"]
    if fx["source"] != "em":
        out["flags"].append("FX_FALLBACK: 汇率来自 frankfurter(ECB参考价)，与中间价略有差异，报告需注明")

    # ---- 期界 ----
    all_dates = [d for s in out["stocks"].values() for d, _ in s["close"]] or \
                [d for f_ in out["funds"].values() for d, _ in f_["nav"]]
    d_start, d_end = period_bounds(all_dates, period)
    out["d_start"], out["d_end"] = d_start, d_end
    log.info(f"期界: {d_start} -> {d_end}")

    # ---- 除净检测（限定报告窗口） ----
    for code, s in out["stocks"].items():
        div = False
        if s["source"] == "em":
            cm = dict(s["close"])
            if d_start in cm and d_end in cm and s["_adj"]:
                r0 = s["_adj"].get(d_start, cm[d_start]) / cm[d_start]
                r1 = s["_adj"].get(d_end, cm[d_end]) / cm[d_end]
                div = abs(r0 - r1) / max(r1, 1e-9) > 0.001
        else:
            div = any(d_start < d <= d_end for d in s["_corp_actions"])
        s["dividend_flag"] = div
        if div:
            out["flags"].append(f"CORP_ACTION: {code} {s['name']} 报告窗口内存在除净/派息，收益口径需人工核对")
        del s["_adj"], s["_corp_actions"]

    with open(os.path.join(period_dir, "02_market.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log.info(f"===== S1 完成: funds={len(out['funds'])} stocks={len(out['stocks'])} flags={len(out['flags'])} =====")
    for fl in out["flags"]:
        log.warning(f"flag: {fl}")
    return 0 if not any(f_.startswith("UNRESOLVED") for f_ in out["flags"]) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
