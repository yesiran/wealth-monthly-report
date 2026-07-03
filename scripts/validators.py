#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤间校验门：每步产物在进入下一步前必须通过对应 validate_*。
每个函数返回 (ok: bool, issues: [str])。run.py 在步骤间调用；tests/ 里做回归。"""
import json, os, re


def _load(fp):
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


# ---------------- S0: holdings（泛化 schema） ----------------
# 以 "WARN:" 开头的条目是提示不拦截；其余为硬性错误。

def validate_holdings(fp):
    import lib
    issues = []
    try:
        H = _load(fp)
    except Exception as e:
        return False, [f"JSON 解析失败: {e}"]
    for k in ("asof", "period", "positions", "accounts"):
        if k not in H:
            issues.append(f"缺字段: {k}")
    if not re.match(r"^\d{4}-\d{2}$", H.get("period", "")):
        issues.append("period 格式应为 YYYY-MM")
    acct_pnl = {}
    for i, p in enumerate(H.get("positions", [])):
        kind, market, _ = lib.norm_position(p)
        if kind == "stock":
            for k in ("code", "name", "shares"):
                if k not in p:
                    issues.append(f"positions[{i}] 股票缺 {k}")
            if "cost_px" not in p:
                issues.append(f"WARN: positions[{i}] {p.get('name')} 无成本价，累计收益将无法计算")
            if market not in lib.STOCK_MARKETS:
                issues.append(f"WARN: positions[{i}] {p.get('name')} market={market} 暂不支持定价，将列入未纳入")
            shot = p.get("screenshot", {})
            if shot.get("pnl_total") is not None:
                acct_pnl.setdefault(p.get("acct", "?"), 0.0)
                acct_pnl[p.get("acct", "?")] += shot["pnl_total"]
        elif kind == "fund":
            if "name_display" not in p:
                issues.append(f"positions[{i}] 基金缺 name_display")
            shot = p.get("screenshot", {})
            if "amount" not in shot:
                issues.append(f"positions[{i}] 基金缺 screenshot.amount（无金额无法反推份额）")
            if shot.get("pnl_yday") is None:
                issues.append(f"WARN: positions[{i}] {p.get('name_display')} 缺昨日收益，基金身份只能名称匹配（低置信）")
            if shot.get("pnl_total") is None:
                issues.append(f"WARN: positions[{i}] {p.get('name_display')} 缺持仓收益，成本与买入日将无法反推")
        else:
            issues.append(f"WARN: positions[{i}] 类型 {kind} 暂不支持定价，将列入未纳入")
    # 账户级盈亏交叉验证（账户提供了总盈亏才检查——识图防错的关键）
    for aid, acc in H.get("accounts", {}).items():
        if acc.get("pnl_total") is not None and aid in acct_pnl:
            if abs(acct_pnl[aid] - acc["pnl_total"]) > 1.0:
                issues.append(f"账户[{aid}]盈亏交叉验证失败: 各持仓之和 {acct_pnl[aid]:.2f} vs 账户 {acc['pnl_total']:.2f}")
    hard = [i for i in issues if not i.startswith("WARN:")]
    return not hard, issues


# ---------------- S1: market ----------------

def validate_market(fp):
    issues = []
    try:
        M = _load(fp)
    except Exception as e:
        return False, [f"JSON 解析失败: {e}"]
    for k in ("d_start", "d_end", "funds", "stocks", "fx", "resolution"):
        if k not in M:
            issues.append(f"缺字段: {k}")
    for fl in M.get("flags", []):
        if fl.startswith(("UNRESOLVED", "AMBIGUOUS")):
            issues.append(f"S1 flag 需处理: {fl}")
    for code, fdata in M.get("funds", {}).items():
        dates = [d for d, _ in fdata["nav"]]
        if M.get("d_end") not in dates:
            issues.append(f"基金 {code} 缺 {M.get('d_end')} 净值（可能尚未披露，晚些重跑 S1）")
        if dates and M.get("d_start") and min(dates) > M["d_start"]:
            issues.append(f"基金 {code} 净值序列未覆盖期初 {M['d_start']}（最早 {min(dates)}），需增大抓取页数")
    for code, s in M.get("stocks", {}).items():
        dates = [d for d, _ in s["close"]]
        for d in (M.get("d_start"), M.get("d_end")):
            if d not in dates:
                issues.append(f"股票 {code} 缺 {d} 收盘价")
    return not issues, issues


# ---------------- S2: returns ----------------

def validate_returns(fp, holdings_fp=None):
    issues = []
    try:
        R = _load(fp)
    except Exception as e:
        return False, [f"JSON 解析失败: {e}"]
    if R.get("errors"):
        issues += [f"S2 error: {e}" for e in R["errors"]]
    hs = R.get("holdings", [])
    s = R.get("summary", {})
    if holdings_fp:
        H = _load(holdings_fp)
        n_excl = len(R.get("excluded_auto", []))
        if len(hs) + n_excl != len(H["positions"]):
            issues.append(f"标的数不闭合: returns {len(hs)} + 未纳入 {n_excl} != holdings {len(H['positions'])}")
    # 内部一致性：分账户盈亏与总盈亏对得上
    hk_pnl = sum(h["pnl_m"] for h in hs if h["ccy"] == "HKD")
    cn_pnl = sum(h["pnl_m"] for h in hs if h["ccy"] == "CNY")
    if abs(hk_pnl - s.get("hk_pnl_m", 0)) > 1:
        issues.append("港股盈亏汇总不一致")
    if abs(cn_pnl - s.get("cn_pnl_m", 0)) > 1:
        issues.append("基金盈亏汇总不一致")
    total = hk_pnl * s.get("fx_end", 0) + cn_pnl
    if abs(total - s.get("total_pnl_m_cny", 0)) > 2:
        issues.append(f"总盈亏折算不一致: {total:.2f} vs {s.get('total_pnl_m_cny')}")
    w = sum(h.get("weight_end", 0) for h in hs)
    if abs(w - 1) > 0.001:
        issues.append(f"权重合计 {w:.4f} != 1")
    for h in hs:
        if not h.get("series"):
            issues.append(f"{h['code']} 缺走势序列")
        if h.get("partial") and h.get("val_start") is not None:
            issues.append(f"{h['code']} partial 但有期初值，口径矛盾")
    return not issues, issues


# ---------------- S4: research note ----------------

REQUIRED_SECTIONS = ["大事记", "表现", "催化剂", "多空"]

def validate_research(fp):
    issues = []
    with open(fp, encoding="utf-8") as f:
        text = f.read()
    if len(text) < 800:
        issues.append(f"{os.path.basename(fp)} 内容过短({len(text)}字)")
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            issues.append(f"{os.path.basename(fp)} 缺章节: {sec}")
    if "【事实】" not in text and "| 事实" not in text and "事实" not in text:
        issues.append(f"{os.path.basename(fp)} 无事实标注")
    if not re.search(r"https?://", text):
        issues.append(f"{os.path.basename(fp)} 无任何来源链接")
    return not issues, issues


# ---------------- S5: narrative ----------------

TOKEN_RE = re.compile(r"\{\{([a-zA-Z0-9_.]+)\}\}")

def validate_narrative(fp, returns_fp):
    issues = []
    try:
        N = _load(fp)
    except Exception as e:
        return False, [f"{os.path.basename(fp)} JSON 解析失败: {e}"]
    R = _load(returns_fp)
    from s6_build_html import build_token_table  # 复用同一份 token 表，保证口径一致
    tokens = build_token_table(R)
    for k in ("code", "title", "subtitle", "timeline", "why_html", "forward_html", "predictions"):
        if k not in N:
            issues.append(f"{os.path.basename(fp)} 缺字段: {k}")
    if not any(h["code"] == N.get("code") for h in R["holdings"]):
        issues.append(f"code {N.get('code')} 不在 returns.holdings 中")
    if not (3 <= len(N.get("timeline", [])) <= 10):
        issues.append(f"timeline 条数 {len(N.get('timeline', []))} 不在 3~10")
    for t in N.get("timeline", []):
        if not t.get("date") or not t.get("text"):
            issues.append("timeline 条目缺 date/text")
    preds = N.get("predictions", [])
    if not (1 <= len(preds) <= 3):
        issues.append(f"predictions 条数 {len(preds)} 不在 1~3")
    for p in preds:
        if not p.get("text") or not p.get("window"):
            issues.append("prediction 缺 text/window")
    # 占位符全部可解析
    blob = json.dumps(N, ensure_ascii=False)
    for tok in TOKEN_RE.findall(blob):
        if tok not in tokens:
            issues.append(f"未知占位符 {{{{{tok}}}}}")
    return not issues, issues


def validate_overview(fp, returns_fp):
    issues = []
    try:
        O = _load(fp)
    except Exception as e:
        return False, [f"overview JSON 解析失败: {e}"]
    R = _load(returns_fp)
    from s6_build_html import build_token_table
    tokens = build_token_table(R)
    for k in ("theme_title", "cover_lead", "brief_bullets", "checkup", "calendar"):
        if k not in O:
            issues.append(f"overview 缺字段: {k}")
    if not (3 <= len(O.get("brief_bullets", [])) <= 8):
        issues.append("brief_bullets 应为 3~8 条")
    if len(O.get("checkup", [])) != 4:
        issues.append("checkup 应为 4 条")
    if len(O.get("calendar", [])) < 6:
        issues.append("calendar 少于 6 条")
    blob = json.dumps(O, ensure_ascii=False)
    for tok in TOKEN_RE.findall(blob):
        if tok not in tokens:
            issues.append(f"未知占位符 {{{{{tok}}}}}")
    return not issues, issues


# ---------------- S6: html ----------------

def validate_html(fp, returns_fp):
    issues = []
    with open(fp, encoding="utf-8") as f:
        html = f.read()
    if "{{" in html:
        m = re.findall(r"\{\{[^}]*\}\}", html)[:5]
        issues.append(f"存在未解析占位符: {m}")
    if "%%" in html:
        issues.append("存在未替换模板标记 %%")
    R = _load(returns_fp)
    for h in R["holdings"]:
        if h["name"].split("(")[0][:6] not in html:
            issues.append(f"HTML 缺标的: {h['name']}")
    key = f"{R['summary']['total_pnl_m_cny']:+,.0f}".replace("+", "")
    if key not in html:
        issues.append(f"HTML 缺组合盈亏关键数字 {key}")
    n_svg = html.count("<svg")
    if n_svg < len(R["holdings"]) + 2:
        issues.append(f"SVG 数量 {n_svg} < 预期 {len(R['holdings']) + 2}")
    return not issues, issues


if __name__ == "__main__":
    import sys
    fn, args = sys.argv[1], sys.argv[2:]
    ok, issues = globals()[f"validate_{fn}"](*args)
    print(f"[validate_{fn}] {'PASS' if ok else 'FAIL'}")
    for i in issues:
        print("  ✗", i)
    sys.exit(0 if ok else 1)
