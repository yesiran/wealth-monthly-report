#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S6 组装出版：03_returns.json + 06_narrative/*.json (+05_review.json) -> 07_report.html
- 图表(SVG)与全部数字由本脚本从 returns.json 生成；叙事 JSON 里的数字一律是 {{token}} 占位符
- build_token_table() 是占位符的唯一定义处，validators.py 复用它
用法: python3 s6_build_html.py <period_dir>
"""
import json, glob, os, re, sys

NAVY = "#1B2A4A"; GOLD = "#B08D2E"; UP = "#c9463d"; DOWN = "#0f7b46"
INK2 = "#52514e"; MUTED = "#898781"; HAIR = "#e3e2db"
CIRCLED = "❶❷❸❹❺❻❼❽❾❿⓫⓬"


# ---------------- 格式化 ----------------

def pct(v, dp=2):
    return f"{v * 100:+.{dp}f}%"

def thou(v):
    return f"{v:+,.0f}" if v < 0 else f"{v:+,.0f}"

def thou_u(v):
    return f"{v:,.0f}"

def wan(v):
    return f"{v / 10000:.1f}万"

def px_fmt(v):
    if v is None:
        return "—"
    s = f"{v:,.4f}".rstrip("0").rstrip(".")
    return s if "." in s or v >= 100 else f"{v:,.2f}"


def build_token_table(R):
    """占位符 -> 字符串。叙事 JSON 中可用的全部数字词表。"""
    T = {}
    s = R["summary"]
    T["sum.period"] = R["period"]
    T["sum.d_start"] = R["d_start"]; T["sum.d_end"] = R["d_end"]
    T["sum.total_pnl_m_cny"] = thou(s["total_pnl_m_cny"])
    T["sum.port_ret_m"] = pct(s["port_ret_m"])
    T["sum.total_end_cny"] = thou_u(s["total_end_cny"])
    T["sum.hk_ret_m"] = pct(s["hk_ret_m"])
    T["sum.hk_pnl_m"] = thou(s["hk_pnl_m"])
    T["sum.cn_pnl_m"] = thou(s["cn_pnl_m"])
    T["sum.cn_ret_m"] = pct(s["cn_ret_m"])
    T["sum.futu_debt_wan"] = wan(s["futu_debt_hkd"])
    T["sum.fx_start"] = f"{s['fx_start']:.4f}"; T["sum.fx_end"] = f"{s['fx_end']:.4f}"
    for k, b in R["benchmarks"].items():
        T[f"bench.{k}"] = pct(b["ret"])
        T[f"bench.{k}.name"] = b["name"]
    for h in R["holdings"]:
        c = h["code"]
        T[f"h.{c}.name"] = h["name"]
        T[f"h.{c}.ret_m"] = pct(h["ret_m"])
        T[f"h.{c}.pnl_m"] = thou(h["pnl_m"])
        T[f"h.{c}.ccy"] = h["ccy"]
        T[f"h.{c}.val_end"] = thou_u(h["val_end"])
        T[f"h.{c}.val_end_wan"] = wan(h["val_end"])
        T[f"h.{c}.weight_end"] = f"{h['weight_end'] * 100:.1f}%"
        T[f"h.{c}.px_start"] = px_fmt(h.get("px_start"))
        T[f"h.{c}.px_end"] = px_fmt(h["px_end"])
        T[f"h.{c}.ret_total"] = pct(h["ret_total"], 1)
        T[f"h.{c}.pnl_total"] = thou(h["pnl_total"])
        is_stock = h["type"] in ("stock", "hk_stock")
        T[f"h.{c}.shares"] = f"{h['shares']:,g}" if is_stock else f"{h['shares']:,.1f}"
        if is_stock:
            T[f"h.{c}.cost_px"] = px_fmt(h.get("cost_px"))
        else:
            T[f"h.{c}.cost_amt_wan"] = wan(h["cost_amt"])
            T[f"h.{c}.buy_date"] = h.get("buy_date") or "—"
    return T


TOKEN_RE = re.compile(r"\{\{([a-zA-Z0-9_.]+)\}\}")

def resolve(text, T):
    def rep(m):
        k = m.group(1)
        if k not in T:
            raise KeyError(f"未知占位符 {{{{{k}}}}}")
        return T[k]
    return TOKEN_RE.sub(rep, text)


# ---------------- SVG 图表 ----------------

def spark_svg(series, w=150, h=42, color=NAVY, mark_date=None):
    vals = [v for _, v in series]
    mn, mx = min(vals), max(vals); rng = (mx - mn) or 1e-9
    n = len(vals)
    pts = [(6 + i / max(n - 1, 1) * (w - 16), h - 8 - (v - mn) / rng * (h - 18)) for i, v in enumerate(vals)]
    line = "M" + " L".join("%.1f,%.1f" % p for p in pts)
    area = line + " L%.1f,%d L%.1f,%d Z" % (pts[-1][0], h - 3, pts[0][0], h - 3)
    mark = ""
    if mark_date:
        for i, (d, _) in enumerate(series):
            if d == mark_date:
                mark = '<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fff" stroke-width="2"/>' % (*pts[i], GOLD)
    return ('<svg class="spark" viewBox="0 0 %d %d" width="%d" height="%d">'
            '<path d="%s" fill="%s" opacity="0.08"/>'
            '<path d="%s" fill="none" stroke="%s" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            '%s<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fff" stroke-width="2"/></svg>'
            % (w, h, w, h, area, color, line, color, mark, pts[-1][0], pts[-1][1], color))


def chart_returns(R):
    rows = sorted(R["holdings"], key=lambda h: h["ret_m"], reverse=True)
    vals = [h["ret_m"] * 100 for h in rows]
    xmin = min(vals + [0]) - 2.2; xmax = max(vals + [0]) + 2.2
    L, Rt, top, pitch, bh = 208, 692, 14, 27, 14
    span = Rt - L
    X = lambda v: L + (v - xmin) / (xmax - xmin) * span
    zx = X(0)
    n = len(rows)
    hgt = top + n * pitch + 24
    p = ['<svg viewBox="0 0 720 %d" width="100%%" style="max-width:720px">' % hgt]
    p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#c3c2b7" stroke-width="1"/>' % (zx, top - 6, zx, top + n * pitch + 2))
    step = 10 if (xmax - xmin) > 14 else 5
    g = int(xmin // step) * step
    while g <= xmax:
        if abs(g) >= step / 2:
            gx = X(g)
            p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1"/>' % (gx, top - 2, gx, top + n * pitch + 2, HAIR))
            p.append('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%d%%</text>' % (gx, top + n * pitch + 16, MUTED, g))
        g += step
    p.append('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">0</text>' % (zx, top + n * pitch + 16, MUTED))
    for i, h in enumerate(rows):
        v = h["ret_m"] * 100
        y = top + i * pitch + (pitch - bh) / 2
        cy = y + bh / 2
        flag = "※" if h.get("partial") else ""
        fs = 11.5 if len(h["name"]) <= 15 else 10
        p.append('<text x="200" y="%.1f" font-size="%s" fill="%s" text-anchor="end" dominant-baseline="middle">%s%s</text>' % (cy + 0.5, fs, INK2, h["name"], flag))
        if v >= 0:
            x1 = X(v); wd = max(x1 - zx, 2)
            p.append('<path d="M%.1f,%.1f h%.1f a3,3 0 0 1 3,3 v%.1f a3,3 0 0 1 -3,3 h-%.1f Z" fill="%s"/>' % (zx, y, wd - 3, bh - 6, wd - 3, UP))
            p.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="600" fill="#333" dominant-baseline="middle">%+.2f%%</text>' % (x1 + 6, cy + 0.5, v))
        else:
            x1 = X(v); wd = max(zx - x1, 2)
            p.append('<path d="M%.1f,%.1f h%.1f v%.1f h-%.1f a3,3 0 0 1 -3,-3 v-%.1f a3,3 0 0 1 3,-3 Z" fill="%s"/>' % (x1 + 3, y, wd - 3, bh, wd - 3, bh - 6, DOWN))
            if x1 - 60 < L:
                p.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="700" fill="#fff" dominant-baseline="middle">%.2f%%</text>' % (x1 + 9, cy + 0.5, v))
            else:
                p.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="600" fill="#333" text-anchor="end" dominant-baseline="middle">%.2f%%</text>' % (x1 - 6, cy + 0.5, v))
    p.append('</svg>')
    return "".join(p)


def chart_bench(R, bench_order):
    cols = [("本组合", R["summary"]["port_ret_m"] * 100, True)]
    for k in bench_order:
        if k in R["benchmarks"]:
            b = R["benchmarks"][k]
            cols.append((b["name"], b["ret"] * 100, False))
    vals = [v for _, v, _ in cols]
    vmax = max(vals + [0]) + 1.8; vmin = min(vals + [0]) - 1.8
    W, Hh, top, bot = 720, 190, 26, 34
    plot_h = Hh - top - bot
    Y = lambda v: top + (vmax - v) / (vmax - vmin) * plot_h
    zy = Y(0)
    n = len(cols)
    bw = 66; gap = (W - 100 - n * bw) / max(n - 1, 1)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="max-width:720px">' % (W, Hh)]
    p.append('<line x1="40" y1="%.1f" x2="%d" y2="%.1f" stroke="#c3c2b7" stroke-width="1"/>' % (zy, W - 20, zy))
    for i, (name, v, em) in enumerate(cols):
        x = 60 + i * (bw + gap)
        c = UP if v >= 0 else DOWN
        fw = "700" if em else "600"
        if v >= 0:
            y1 = Y(v); hh = max(zy - y1, 2)
            p.append('<path d="M%.1f,%.1f a3,3 0 0 1 3,-3 h%.1f a3,3 0 0 1 3,3 v%.1f h-%.1f Z" fill="%s"/>' % (x, y1 + 3, bw - 6, hh - 3, bw, c))
            p.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="%s" fill="#333" text-anchor="middle">%+.2f%%</text>' % (x + bw / 2, y1 - 7, fw, v))
        else:
            hh = max(Y(v) - zy, 2)
            p.append('<path d="M%.1f,%.1f v%.1f a3,3 0 0 1 -3,3 h-%.1f a3,3 0 0 1 -3,-3 v-%.1f Z" fill="%s"/>' % (x + bw, zy, hh - 3, bw - 6, hh - 3, c))
            p.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="%s" fill="#333" text-anchor="middle">%.2f%%</text>' % (x + bw / 2, Y(v) + 16, fw, v))
        p.append('<text x="%.1f" y="%d" font-size="12" font-weight="%s" fill="%s" text-anchor="middle">%s</text>' % (x + bw / 2, Hh - 8, fw, NAVY if em else INK2, name))
    p.append('</svg>')
    return "".join(p)


# ---------------- HTML 组装 ----------------

def load_css():
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "report.css")
    with open(fp, encoding="utf-8") as f:
        return f.read()


def holdings_table(R, mon):
    rows_sorted = sorted(R["holdings"], key=lambda h: h["weight_end"], reverse=True)
    max_w = max(h["weight_end"] for h in rows_sorted)
    tr = []
    for h in rows_sorted:
        cls = lambda v: "pos" if v >= 0 else "neg"
        is_stock = h["type"] in ("stock", "hk_stock")
        code_sfx = f" {h['code']}" if is_stock else ""
        shares = f"{h['shares']:,g}股" if is_stock else f"{h['shares']:,.1f}份"
        star = "※" if h.get("partial") else ""
        tr.append(
            f"<tr><td class='nm'>{h['name']}{code_sfx}</td><td>{shares}</td>"
            f"<td>{px_fmt(h.get('px_start'))}</td><td>{px_fmt(h['px_end'])}</td>"
            f"<td class='{cls(h['ret_m'])}'>{pct(h['ret_m'])}{star}</td>"
            f"<td class='{cls(h['pnl_m'])}'>{thou(h['pnl_m'])}</td>"
            f"<td>{thou_u(h['val_end'])} {h['ccy']}</td>"
            f"<td class='{cls(h['ret_total'])}'>{pct(h['ret_total'], 1)}</td>"
            f"<td><div class='meter'><div class='meter-fill' style='width:{h['weight_end'] / max_w * 100:.0f}%;background:{NAVY}'></div></div> {h['weight_end'] * 100:.1f}%</td></tr>")
    s = R["summary"]
    hk_tot_ret = sum(x['pnl_total'] for x in R['holdings'] if x['ccy'] == 'HKD')
    hk_cost = sum(x['val_end'] for x in R['holdings'] if x['ccy'] == 'HKD') - hk_tot_ret
    foot = (
        f"<tr><td class='nm'>港币资产小计（HKD）</td><td></td><td></td><td></td>"
        f"<td class='neg' >{pct(s['hk_ret_m'])}</td><td class='{'pos' if s['hk_pnl_m'] >= 0 else 'neg'}'>{thou(s['hk_pnl_m'])}</td>"
        f"<td>{thou_u(s['hk_val_end'])}</td><td class='{'pos' if hk_tot_ret >= 0 else 'neg'}'>{pct(hk_tot_ret / hk_cost, 1)}</td><td></td></tr>"
        f"<tr><td class='nm'>人民币资产小计（CNY）</td><td></td><td></td><td></td>"
        f"<td class='{'pos' if s['cn_ret_m'] >= 0 else 'neg'}'>{pct(s['cn_ret_m'])}</td><td class='{'pos' if s['cn_pnl_m'] >= 0 else 'neg'}'>{thou(s['cn_pnl_m'])}</td>"
        f"<td>{thou_u(s['cn_val_end'])}</td><td></td><td></td></tr>"
        f"<tr><td class='nm'>组合合计（折人民币）</td><td></td><td></td><td></td>"
        f"<td class='{'pos' if s['port_ret_m'] >= 0 else 'neg'}'>{pct(s['port_ret_m'])}</td><td class='{'pos' if s['total_pnl_m_cny'] >= 0 else 'neg'}'>{thou(s['total_pnl_m_cny'])}</td>"
        f"<td>{thou_u(s['total_end_cny'])}</td><td></td><td></td></tr>")
    head = (f"<thead><tr><th>标的</th><th>份额/股数</th><th>期初价</th><th>期末价</th>"
            f"<th>{mon}涨跌</th><th>{mon}盈亏</th><th>期末市值</th><th>累计收益</th><th>占比</th></tr></thead>")
    return f"<table>{head}<tbody>{''.join(tr)}</tbody><tfoot>{foot}</tfoot></table>"


def holding_card(idx, h, N, T):
    color = lambda v: UP if v >= 0 else DOWN
    star = "※" if h.get("partial") else ""
    mark = h.get("buy_date") if h.get("partial") else None
    tl = "".join(f"<li><span class='d'>{t['date']}</span><span>{resolve(t['text'], T)}</span></li>"
                 for t in N["timeline"])
    preds = "".join(
        f"<div class='pred'><span class='arrow'>▸</span><span>{resolve(p['text'], T)}</span>"
        f"<span class='win'>验证窗口：{p['window']}</span></div>" for p in N["predictions"])
    bg = f"<p style='margin-top:6px;font-size:10pt;color:{INK2}'>{resolve(N['background_html'], T)}</p>" if N.get("background_html") else ""
    return f"""
<div class="hold">
  <div class="hh">
    <div class="idx">{CIRCLED[idx]}</div>
    <div class="nm"><div class="n1">{resolve(N['title'], T)}</div><div class="n2">{resolve(N['subtitle'], T)}</div></div>
    <div class="chip"><div class="l">本月涨跌</div><div class="v" style="color:{color(h['ret_m'])}">{pct(h['ret_m'])}{star}</div></div>
    <div class="chip"><div class="l">本月盈亏</div><div class="v" style="color:{color(h['pnl_m'])}">{thou(h['pnl_m'])} {h['ccy']}</div></div>
    <div class="chip"><div class="l">期末市值</div><div class="v">{wan(h['val_end'])} {h['ccy']}</div></div>
    <div class="chip"><div class="l">累计收益</div><div class="v" style="color:{color(h['ret_total'])}">{pct(h['ret_total'], 1)}</div></div>
    {spark_svg(h['series'], mark_date=mark)}
  </div>
  <div class="hbody">
    <div class="blk"><div class="bt">发生了什么</div><ul class="tl">{tl}</ul>{bg}</div>
    <div class="blk"><div class="bt">为什么</div>{resolve(N['why_html'], T)}</div>
    <div class="blk fwd"><div class="bt">往前看</div>{resolve(N['forward_html'], T)}
      <div class="preds"><div class="pt">📌 预判存档（下期复盘）</div>{preds}</div>
    </div>
  </div>
</div>"""


def review_section(review, T):
    if not review:
        return ""
    rows = "".join(
        f"<tr><td>{r['name']}</td><td style='text-align:left;white-space:normal'>{resolve(r['pred_text'], T)}</td>"
        f"<td>{r['window']}</td><td style='font-size:13px'>{r['verdict']}</td>"
        f"<td style='text-align:left;white-space:normal'>{resolve(r.get('evidence', ''), T)}</td></tr>"
        for r in review)
    return f"""
<div class="sec"><div class="kick">REVIEW</div><h2>上期预判复盘</h2>
<div class="note">上期报告立下的预判，本期逐条对照事实打分：✓命中 / ✗落空 / ◐部分 / ⏳未到期。</div></div>
<table class="cal"><thead><tr><th>标的</th><th>上期预判</th><th>窗口</th><th>结果</th><th>证据</th></tr></thead>
<tbody>{rows}</tbody></table>"""


def main(period_dir):
    with open(os.path.join(period_dir, "03_returns.json"), encoding="utf-8") as f:
        R = json.load(f)
    T = build_token_table(R)
    nd = os.path.join(period_dir, "06_narrative")
    with open(os.path.join(nd, "overview.json"), encoding="utf-8") as f:
        O = json.load(f)
    narratives = {}
    for fp in glob.glob(os.path.join(nd, "[0-9]*.json")):
        with open(fp, encoding="utf-8") as f:
            n = json.load(f)
        narratives[n["code"]] = n
    review = None
    rf = os.path.join(period_dir, "05_review.json")
    if os.path.exists(rf):
        with open(rf, encoding="utf-8") as f:
            review = json.load(f)

    y, m = map(int, R["period"].split("-"))
    mon = f"{m}月"
    issue = (y - 2026) * 12 + (m - 6) + 1
    s = R["summary"]

    cards = []
    for i, h in enumerate(R["holdings"]):
        if h["code"] not in narratives:
            raise SystemExit(f"缺叙事文件: {h['code']}")
        cards.append(holding_card(i, h, narratives[h["code"]], T))

    briefs = "".join(f"<li>{resolve(b, T)}</li>" for b in O["brief_bullets"])
    checkups = "".join(
        f"<div class='callout'><div class='ct'>{c['title']}</div><p>{resolve(c['html'], T)}</p></div>"
        for c in O["checkup"])
    cal_rows = "".join(
        f"<tr><td>{r['date']}</td><td>{r['event']}{' ★' if r.get('star') else ''}</td>"
        f"<td>{''.join(f'<span class=tag>{t}</span>' for t in r.get('tags', []))}{r.get('note', '')}</td></tr>"
        for r in O["calendar"])
    meth_extra = "".join(f"<li>{resolve(x, T)}</li>" for x in O.get("methodology_extra", []))
    if R.get("excluded"):
        items = "；".join(f"{e['desc']}（{e.get('reason', e.get('ccy', ''))}）" if isinstance(e, dict) else str(e)
                          for e in R["excluded"])
        meth_extra += f"<li><b>未纳入分析的资产</b>：{items}。</li>"
    cf = O.get("cashflow_note", {"value": "—", "label": ""})

    cover_stats = f"""
    <div class="cstat"><div class="l">期末组合市值（人民币）</div><div class="v">¥ {thou_u(s['total_end_cny'])}</div><div class="d">{O.get('cover_stat4_note', '')}</div></div>
    <div class="cstat"><div class="l">{mon}盈亏（人民币）</div><div class="v" style="color:{'#f0b8b3' if s['total_pnl_m_cny'] >= 0 else '#8fd6a8'}">{thou(s['total_pnl_m_cny'])}</div><div class="d">月收益率 {pct(s['port_ret_m'])}</div></div>
    <div class="cstat"><div class="l">{mon}现金流入</div><div class="v">{cf['value']}</div><div class="d">{cf['label']}</div></div>
    <div class="cstat"><div class="l">持仓标的</div><div class="v">{len(R['holdings'])} 只</div><div class="d">港股{sum(1 for h in R['holdings'] if h['ccy'] == 'HKD')} + 场外基金{sum(1 for h in R['holdings'] if h['ccy'] == 'CNY')}</div></div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>叶思染财富月报 · {y}年{mon}</title>
<style>{load_css()}</style></head><body>

<div class="cover">
  <div class="kicker">YSR WEALTH MONTHLY · 第 {issue} 期</div>
  <h1>叶思染财富月报</h1>
  <div class="sub">{y}年{mon} · 统计区间 {R['d_start']} 至 {R['d_end']} · 出品日期 {O.get('publish_date', '')}</div>
  <div class="rule"></div>
  <div class="theme">本月主题｜{O['theme_title']}</div>
  <div class="lead">{resolve(O['cover_lead'], T)}</div>
  <div class="cstats">{cover_stats}</div>
</div>

<div class="sec"><div class="kick">PART 01</div><h2>本月速览</h2></div>
<div class="brief"><ul>{briefs}</ul></div>

<div class="figure">
  <div style="font-size:12px;font-weight:700;color:{NAVY};margin-bottom:4px">{mon}收益率：本组合 vs 市场基准</div>
  {chart_bench(R, O.get('bench_order', list(R['benchmarks'].keys())))}
  <div class="cap">组合收益率口径：{mon}盈亏 ÷（期初持仓市值+月中新买入成本），人民币计价。指数为价格指数。</div>
</div>

{review_section(review, T)}

<div class="sec"><div class="kick">PART 02</div><h2>标的收益总览</h2>
<div class="note">份额说明：港股股数直接取自截图；基金份额由「持仓金额÷当日净值」反算，并用截图中「昨日收益」逐只交叉验证。</div></div>

<div class="figure">
  <div style="font-size:12px;font-weight:700;color:{NAVY};margin-bottom:4px">各标的{mon}涨跌幅（{R['d_start']} → {R['d_end']}）</div>
  {chart_returns(R)}
  <div class="cap">※ 为月中新买入标的，其「本月收益」为买入以来收益，与其余标的口径不同。红=上涨，绿=下跌；条形方向与数值符号同时表达涨跌。</div>
</div>

{holdings_table(R, mon)}
<div class="cap" style="font-size:10px;color:{MUTED};margin-top:6px">汇率：港币中间价 {R['d_start']}={s['fx_start']:.4f}、{R['d_end']}={s['fx_end']:.4f}。累计收益按持仓成本计算。{resolve(O.get('table_note', ''), T)}</div>

<div class="pgbrk"></div>
<div class="sec"><div class="kick">PART 03</div><h2>逐个标的解读</h2>
<div class="note">每个标的按「发生了什么 → 为什么 → 往前看」展开；文末的<b>预判存档</b>是本月报的立场记录，下期逐条复盘对错。</div></div>
{''.join(cards)}

<div class="pgbrk"></div>
<div class="sec"><div class="kick">PART 04</div><h2>组合体检</h2></div>
<div class="grid2">{checkups}</div>

<div class="sec"><div class="kick">PART 05</div><h2>未来30天观察日历</h2>
<div class="note">全部为已公告事件或有明确日期口径的市场预期；打★的是对本组合影响最直接的节点。</div></div>
<table class="cal"><thead><tr><th style="width:92px">日期</th><th>事件</th><th style="width:210px">影响持仓</th></tr></thead>
<tbody>{cal_rows}</tbody></table>

<div class="sec"><div class="kick">PART 06</div><h2>方法与数据说明</h2></div>
<div class="meth"><ul>
<li><b>持仓来源</b>：券商/银行App持仓截图。港股股数直接读取；基金份额=持仓金额÷当日净值反算，并用截图「昨日收益」与「持仓收益」双重校验。</li>
<li><b>估值时点</b>：{R['d_start']}（上月最后交易日）与 {R['d_end']} 收盘价/单位净值；QDII基金按净值日期口径。行情来源：东方财富。汇率为港币兑人民币中间价。</li>
<li><b>月中买入口径</b>：月中新买入标的的「本月收益」为买入以来收益；组合月收益率分母 = 期初持仓市值 + 新买入成本。</li>
{meth_extra}
<li><b>信息来源</b>：公司公告（港交所披露易）、基金定期报告与净值披露、公开财经媒体报道；关键事实均经多源交叉验证，无法核实处已在正文注明。</li>
</ul>
<div class="disclaim">本报告仅为个人投资记录与研究参考，不构成任何投资建议。市场有风险，投资需谨慎。历史收益不代表未来表现；报告中的「预判存档」是用于自我校准的记录机制，而非收益承诺。<br>叶思染财富月报 · 第{issue}期 · {O.get('publish_date', '')}生成</div>
</div>
</body></html>"""

    out = os.path.join(period_dir, "07_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[S6] ok: {out} ({len(html):,} bytes, {len(cards)} cards)")


if __name__ == "__main__":
    main(sys.argv[1])
