#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 收益计算：01_holdings.json + 02_market.json -> 03_returns.json
全部报告数字的唯一产地。泛化规则：
- 股票按 market 归入币种桶（hk→HKD，sh/sz→CNY）；基金→CNY
- 暂不支持定价的持仓（如美股/黄金，S1 未给行情）自动移入 excluded_auto，报告"未纳入"口径披露
用法: python3 s2_compute_returns.py <period_dir>
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import infer_buy_date, get_logger, norm_position

log = get_logger("s2")


def at(series, d):
    m = dict(series)
    if d not in m:
        raise KeyError(f"date {d} not in series")
    return m[d]


def window(series, d_start, d_end):
    return [[d, v] for d, v in sorted(series) if d_start <= d <= d_end]


def main(period_dir):
    with open(os.path.join(period_dir, "01_holdings.json"), encoding="utf-8") as f:
        H = json.load(f)
    with open(os.path.join(period_dir, "02_market.json"), encoding="utf-8") as f:
        M = json.load(f)
    d0, d1 = M["d_start"], M["d_end"]
    fx0, fx1 = at(M["fx"]["close"], d0), at(M["fx"]["close"], d1)
    res_by_disp = {r["display"]: r for r in M["resolution"] if r.get("ok")}
    log.info(f"===== S2 开始: {M['period']} 窗口 {d0}->{d1} fx {fx0}->{fx1} =====")

    holdings, errors, excluded_auto = [], [], []

    for p in H["positions"]:
        kind, market, ccy = norm_position(p)

        if kind == "stock":
            code = p["code"]
            if code not in M.get("stocks", {}):
                excluded_auto.append({"desc": f"{p.get('name', code)}（market={market}）",
                                      "reason": "该市场暂不支持定价，未纳入分析"})
                log.warning(f"移入未纳入: {p.get('name')} market={market}")
                continue
            sh = p["shares"]
            closes = M["stocks"][code]["close"]
            p0, p1 = at(closes, d0), at(closes, d1)
            h = {
                "code": code, "name": p["name"], "acct": p.get("acct", ""), "ccy": ccy,
                "type": "stock", "market": market, "shares": sh, "cost_px": p["cost_px"],
                "px_start": p0, "px_end": p1,
                "ret_m": p1 / p0 - 1, "pnl_m": sh * (p1 - p0),
                "val_start": sh * p0, "val_end": sh * p1,
                "ret_total": p1 / p["cost_px"] - 1, "pnl_total": sh * (p1 - p["cost_px"]),
                "partial": False, "dividend_flag": M["stocks"][code]["dividend_flag"],
                "series": window(closes, d0, d1),
            }
            holdings.append(h)
            log.info(f"股票 {p['name']}: {p0}->{p1} {h['ret_m']*100:+.2f}% pnl_m={h['pnl_m']:,.0f} {ccy}")
            shot = p.get("screenshot", {})
            if shot.get("px") and shot.get("value") and abs(sh * shot["px"] - shot["value"]) > 1:
                errors.append(f"{code} 截图市值不自洽: {sh}×{shot['px']} != {shot['value']}")

        elif kind == "fund":
            disp, shot = p["name_display"], p["screenshot"]
            r = res_by_disp.get(disp)
            if not r:
                errors.append(f"基金未解析: {disp}")
                continue
            code = r["code"]
            nav = M["funds"][code]["nav"]
            snap_d = r["snapshot_nav_date"]
            shares = round(shot["amount"] / at(nav, snap_d), 2)
            if abs(shares - r["shares_fit"]) / shares > 0.001:
                errors.append(f"{code} 份额双算不一致: {shares} vs {r['shares_fit']}")
            has_cost = shot.get("pnl_total") is not None
            cost_amt = round(shot["amount"] - shot.get("pnl_total", 0), 2)
            buy_date = infer_buy_date(nav, shares, cost_amt) if has_cost else None
            n1 = at(nav, d1)
            partial = bool(buy_date and buy_date > d0)
            h = {"code": code, "name": disp, "acct": p.get("acct", ""), "ccy": "CNY",
                 "type": "fund", "shares": shares, "cost_amt": cost_amt,
                 "buy_date": buy_date, "px_end": n1, "val_end": round(shares * n1, 2),
                 "ret_total": shares * n1 / cost_amt - 1,
                 "pnl_total": round(shares * n1 - cost_amt, 2),
                 "partial": partial,
                 "fhsp_in_window": [x for x in M["funds"][code]["fhsp"] if d0 < x[0] <= d1],
                 "series": window(nav, d0, d1)}
            if partial:
                h.update({"px_start": None, "val_start": None,
                          "ret_m": h["ret_total"], "pnl_m": h["pnl_total"]})
            else:
                n0 = at(nav, d0)
                h.update({"px_start": n0, "val_start": round(shares * n0, 2),
                          "ret_m": n1 / n0 - 1, "pnl_m": round(shares * (n1 - n0), 2)})
            if h["fhsp_in_window"]:
                errors.append(f"{code} 窗口内有分红送配 {h['fhsp_in_window']}，收益口径需人工确认")
            holdings.append(h)
            log.info(f"基金 {disp}({code}): 份额={shares} {h['ret_m']*100:+.2f}%{'*' if partial else ''} "
                     f"pnl_m={h['pnl_m']:,.0f} 买入日={buy_date}")

        else:
            # 黄金/理财等暂不支持定价的资产类型
            excluded_auto.append({"desc": p.get("name") or p.get("name_display") or str(p)[:40],
                                  "reason": f"资产类型 {kind} 暂不支持定价，未纳入分析"})
            log.warning(f"移入未纳入: {p.get('name') or p.get('name_display')} type={kind}")

    # ---- 币种桶汇总（HKD 折算，CNY 原币） ----
    hk = [h for h in holdings if h["ccy"] == "HKD"]
    cn = [h for h in holdings if h["ccy"] == "CNY"]
    other_ccy = {h["ccy"] for h in holdings} - {"HKD", "CNY"}
    if other_ccy:
        errors.append(f"存在暂不支持的币种: {other_ccy}")
    hk0 = sum(h["val_start"] for h in hk)
    hk1 = sum(h["val_end"] for h in hk)
    cn0 = sum(h["val_start"] for h in cn if h["val_start"])
    cn1 = sum(h["val_end"] for h in cn)
    cn_pnl = sum(h["pnl_m"] for h in cn)
    new_cost = sum(h["cost_amt"] for h in cn if h.get("partial"))
    base = hk0 * fx0 + cn0 + new_cost
    total_pnl = (hk1 - hk0) * fx1 + cn_pnl
    total_end = hk1 * fx1 + cn1
    for h in holdings:
        v = h["val_end"] * (fx1 if h["ccy"] == "HKD" else 1)
        h["val_end_cny"] = round(v, 2)
        h["weight_end"] = v / total_end

    acc = H["accounts"].get("futu") or next(
        (a for a in H["accounts"].values() if a.get("type") == "margin"), {})
    debt = round(acc.get("market_value", 0) - acc.get("net_assets", 0), 2) if acc else 0

    benchmarks = {}
    for k, b in M["benchmarks"].items():
        b0, b1 = at(b["close"], d0), at(b["close"], d1)
        benchmarks[k] = {"name": b["name"], "start": b0, "end": b1, "ret": b1 / b0 - 1}

    out = {
        "period": M["period"], "d_start": d0, "d_end": d1,
        "holdings": holdings,
        "summary": {
            "hk_val_start": round(hk0, 2), "hk_val_end": round(hk1, 2),
            "hk_pnl_m": round(hk1 - hk0, 2), "hk_ret_m": (hk1 / hk0 - 1) if hk0 else 0,
            "cn_val_start_heldonly": round(cn0, 2), "cn_val_end": round(cn1, 2),
            "cn_pnl_m": round(cn_pnl, 2),
            "cn_ret_m": cn_pnl / (cn0 + new_cost) if (cn0 + new_cost) else 0,
            "base_cny": round(base, 2), "total_pnl_m_cny": round(total_pnl, 2),
            "port_ret_m": total_pnl / base if base else 0,
            "total_end_cny": round(total_end, 2),
            "futu_debt_hkd": debt,
            "fx_start": fx0, "fx_end": fx1,
        },
        "benchmarks": benchmarks,
        "excluded": H.get("excluded", []) + excluded_auto,
        "excluded_auto": excluded_auto,
        "errors": errors,
    }

    with open(os.path.join(period_dir, "03_returns.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    s = out["summary"]
    log.info(f"===== S2 完成: 盈亏 {s['total_pnl_m_cny']:+,.0f} CNY ({s['port_ret_m']*100:+.2f}%) "
             f"期末 {s['total_end_cny']:,.0f} 未纳入 {len(excluded_auto)} errors={len(errors)} =====")
    for e in errors:
        log.error(e)
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
