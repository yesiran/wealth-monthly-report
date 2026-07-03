#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月报工作台回归测试。默认离线（用 tests/fixtures/ + tests/baseline_2026-06/raw/ 缓存），不打网络。
用法:
  python3 tests/run_tests.py            # 全部离线回归
  python3 tests/run_tests.py --smoke    # 附加在线冒烟测试（数据源可用性）
每次改动 scripts/ 后必须跑一遍；run.py 每次启动也会先跑。"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
FIX = os.path.join(HERE, "fixtures")
BASELINE = os.path.join(HERE, "baseline_2026-06")  # 首期黄金基线（已从工作区移入测试区）
sys.path.insert(0, SCRIPTS)

PASS, FAIL = 0, []

def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL.append(name)
        print(f"  ✗ {name}  {detail}")


def approx(a, b, tol):
    return abs(a - b) <= tol


# ================= T1: lib 解析器（离线，用真实缓存响应） =================
def t1_parsers():
    print("[T1] lib 解析器")
    import lib
    raw = os.path.join(BASELINE, "raw")
    with open(os.path.join(raw, "nav_110017_p1.json"), encoding="utf-8") as f:
        rows = lib.parse_fund_nav(f.read())
    check("fund_nav 解析出净值行", len(rows) >= 15)  # lsjz 单页上限已观测到从49漂移为20
    check("fund_nav 字段类型", isinstance(rows[0][1], float) and rows[0][0].count("-") == 2)
    tk = [x for x in os.listdir(raw) if x.startswith("tkline_hk03690")]
    check("腾讯源缓存存在", bool(tk))
    if tk:
        with open(os.path.join(raw, tk[0]), encoding="utf-8") as f:
            rows2, actions = lib.parse_kline_tencent(f.read(), "hk03690")
        m = dict((r["date"], r["close"]) for r in rows2)
        check("腾讯源 美团 6/30 收盘=68.50", approx(m.get("2026-06-30", 0), 68.50, 0.01))
        check("腾讯源 美团 5/29 收盘=73.45", approx(m.get("2026-05-29", 0), 73.45, 0.01))


# ================= T2: 基金身份拟合（黄金case） =================
def t2_fit():
    print("[T2] 基金身份拟合")
    import lib
    raw = os.path.join(BASELINE, "raw")

    def nav_getter(code):
        out = []
        for p in (1, 2):
            fp = os.path.join(raw, f"nav_{code}_p{p}.json")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as f:
                    out.extend(lib.parse_fund_nav(f.read()))
        if not out:
            raise RuntimeError("no cache")
        return out

    # 黄金case1：机器人联接C 必须拟合为 020973，份额≈100746.70
    cands = [("020972", "易方达机器人ETF联接A"), ("020973", "易方达机器人ETF联接C"),
             ("025699", "鹏华国证机器人产业ETF发起式联接C")]
    hits = lib.fit_fund_identity(cands, 156278.28, -2700.01, -2700.01, nav_getter, asof="2026-06-23")
    check("机器人拟合命中 020973", bool(hits) and hits[0][0] == "020973",
          f"hits={[(h[0], h[4]) for h in hits]}")
    if hits:
        check("机器人份额 ≈100746.70", approx(hits[0][3], 100746.70, 0.5))
    # 黄金case2：债基（净值日变仅0.003，测舍入不放大）
    hits2 = lib.fit_fund_identity([("110017", "易方达增强回报债券A")],
                                  99136.65, 213.66, 1273.21, nav_getter, asof="2026-06-23")
    check("债基拟合命中", bool(hits2) and hits2[0][0] == "110017")
    if hits2:
        check("债基份额 ≈71218.86", approx(hits2[0][3], 71218.86, 1.0))
    # 反例：错误的候选不应命中
    hits3 = lib.fit_fund_identity([("023298", "汇添富中证A500指数增强A")],
                                  156278.28, -2700.01, -2700.01, nav_getter, asof="2026-06-23")
    check("错误候选不命中（防误配）", not hits3)
    # 买入日推断
    nav = nav_getter("020973")
    check("机器人买入日=2026-06-18", lib.infer_buy_date(nav, 100746.70, 158978.29) == "2026-06-18")
    nav2 = nav_getter("021034")
    check("电池买入日=2026-05-08", lib.infer_buy_date(nav2, 68482.63, 127726.88) == "2026-05-08")


# ================= T3: S2 黄金数字回归 =================
def t3_returns():
    print("[T3] S2 黄金数字（对照首期人工验证结果）")
    with tempfile.TemporaryDirectory() as td:
        for f in ("01_holdings.json", "02_market.json"):
            with open(os.path.join(FIX, f), encoding="utf-8") as sf, \
                 open(os.path.join(td, f), "w", encoding="utf-8") as df:
                df.write(sf.read())
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "s2_compute_returns.py"), td],
                           capture_output=True, text=True)
        check("S2 退出码=0", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
        with open(os.path.join(td, "03_returns.json"), encoding="utf-8") as f:
            R = json.load(f)
    H = {h["code"]: h for h in R["holdings"]}
    golden_ret = {"03690": -0.0674, "00700": 0.0061, "01810": -0.2282, "09992": -0.1078,
                  "00567": -0.1250, "023298": 0.0296, "013309": -0.0808, "021034": -0.0308,
                  "110017": -0.0079, "020973": -0.0234}
    for code, g in golden_ret.items():
        check(f"{code} 月收益 {g:+.2%}", approx(H[code]["ret_m"], g, 0.0005))
    golden_shares = {"023298": 155277.1, "013309": 142334.6, "021034": 68482.6,
                     "020973": 100746.7, "110017": 71218.9}
    for code, g in golden_shares.items():
        check(f"{code} 份额 {g}", approx(H[code]["shares"], g, 1.0))
    s = R["summary"]
    check("组合月盈亏 = -88,057±5", approx(s["total_pnl_m_cny"], -88057, 5))
    check("组合月收益率 = -5.85%", approx(s["port_ret_m"], -0.0585, 0.0003))
    check("期末总市值 = 1,415,759±5", approx(s["total_end_cny"], 1415759, 5))
    check("港股月盈亏 = -84,708.75", approx(s["hk_pnl_m"], -84708.75, 1))
    check("融资负债 = 251,006.32", approx(s["futu_debt_hkd"], 251006.32, 1))
    check("机器人=月中买入", H["020973"]["partial"] is True and H["020973"]["buy_date"] == "2026-06-18")
    check("电池=全月持有", H["021034"]["partial"] is False)
    check("腾讯无窗口内除净", H["00700"]["dividend_flag"] is False)


# ================= T4: validators 好/坏样本 =================
def t4_validators():
    print("[T4] validators 好/坏样本")
    import validators as V
    ok, _ = V.validate_holdings(os.path.join(FIX, "01_holdings.json"))
    check("holdings 好样本 PASS", ok)
    with open(os.path.join(FIX, "01_holdings.json"), encoding="utf-8") as f:
        bad = json.load(f)
    bad["positions"][0]["screenshot"]["pnl_total"] = 999999  # 打破账户级交叉验证
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(bad, tf, ensure_ascii=False)
        badfp = tf.name
    ok2, issues = V.validate_holdings(badfp)
    check("holdings 坏样本被拒（盈亏交叉验证）", not ok2 and any("交叉验证" in i for i in issues))
    os.unlink(badfp)
    # narrative 坏样本：未知占位符 + 预判缺窗口
    nd = os.path.join(BASELINE, "06_narrative", "03690.json")
    with open(nd, encoding="utf-8") as f:
        n = json.load(f)
    n["why_html"] += "{{h.03690.not_a_token}}"
    n["predictions"][0].pop("window")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(n, tf, ensure_ascii=False)
        badn = tf.name
    ok3, issues3 = V.validate_narrative(badn, os.path.join(FIX, "03_returns.json"))
    check("narrative 坏样本被拒（未知token+缺window）",
          not ok3 and any("占位符" in i for i in issues3) and any("window" in i for i in issues3))
    os.unlink(badn)
    # 排名断言坏样本：小仓位标的自称「第一大持仓」（曾发生：报告出现两个第一大）
    with open(os.path.join(BASELINE, "06_narrative", "09992.json"), encoding="utf-8") as f:
        n2 = json.load(f)
    n2["subtitle"] = "09992.HK · 组合第一大持仓 · " + n2["subtitle"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(n2, tf, ensure_ascii=False)
        badr = tf.name
    ok4, issues4 = V.validate_narrative(badr, os.path.join(FIX, "03_returns.json"))
    check("排名断言坏样本被拒（自称第一大实为小仓位）",
          not ok4 and any("排名断言" in i for i in issues4), str(issues4[:2]))
    os.unlink(badr)
    # 正确的排名断言应放行（美团确为第一大）
    ok5, issues5 = V.validate_narrative(os.path.join(BASELINE, "06_narrative", "03690.json"),
                                        os.path.join(FIX, "03_returns.json"))
    check("正确排名断言放行（美团=第一大）", ok5, str(issues5[:2]))


# ================= T5: S6 组装回归 =================
def t5_build():
    print("[T5] S6 组装（黄金夹具→HTML 不变式）")
    import validators as V
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "s6_build_html.py"),
                        BASELINE], capture_output=True, text=True)
    check("S6 退出码=0", r.returncode == 0, r.stderr[-300:])
    fp = os.path.join(BASELINE, "07_report.html")
    ok, issues = V.validate_html(fp, os.path.join(BASELINE, "03_returns.json"))
    check("HTML 校验 PASS", ok, str(issues[:3]))
    with open(fp, encoding="utf-8") as f:
        html = f.read()
    for kw in ("东边日出西边雨", "预判存档", "未来30天观察日历", "-88,057", "+2.96%", "-22.82%"):
        check(f"HTML 含关键内容「{kw}」", kw in html)
    check("卡片数=10", html.count('class="hold"') == 10)
    check("迷你走势图=10", html.count('class="spark"') == 10)


def t6_research_fixtures():
    print("[T6] 研究笔记夹具（S4 输出格式黄金样本）")
    import glob as _g
    import validators as V
    notes = sorted(_g.glob(os.path.join(BASELINE, "04_research", "研究_*.md")))
    check("研究笔记数量=9", len(notes) == 9, f"实际 {len(notes)}")
    for fp in notes:
        ok, issues = V.validate_research(fp)
        check(f"validate_research {os.path.basename(fp)}", ok, str(issues[:2]))


def t2b_candidates():
    print("[T2b] 候选基金生成（确定性 + 别名命中）")
    import s1_fetch_market as s1
    raw = os.path.join(BASELINE, "raw")
    if not os.path.exists(os.path.join(raw, "fundcode_search.js")):
        check("基线含全量基金列表缓存", False, "缺 fundcode_search.js")
        return
    disp = "易方达国证新能源电池ETF联接发起式C"
    c1 = s1.gen_candidates(disp, raw)
    c2 = s1.gen_candidates(disp, raw)
    codes1 = [c for c, _ in c1]
    # 曾发生：东财简称「储能电池」与全称仅共享「电池」二字，set哈希顺序导致时中时不中
    check("别名基金 021034 必在候选池", "021034" in codes1, str(codes1[:15]))
    check("候选生成完全确定（两次调用一致）", c1 == c2)
    check("相似度排序：021034 进入前10", "021034" in codes1[:10], str(codes1[:10]))


def t7_planner():
    print("[T7] 研究任务自动规划（黄金用例：6月基线）")
    import plan_research
    with open(os.path.join(FIX, "01_holdings.json"), encoding="utf-8") as f:
        H = json.load(f)
    with open(os.path.join(FIX, "02_market.json"), encoding="utf-8") as f:
        M = json.load(f)
    jobs = plan_research.make_plan(H, M)
    stocks = [j for j in jobs if j["kind"] == "stock"]
    themes = {j.get("track"): j for j in jobs if j["kind"] == "theme" and j.get("track")}
    macro = [j for j in jobs if j["id"] == "t_macro"]
    check("个股任务=5", len(stocks) == 5, str([j["id"] for j in stocks]))
    check("主题按跟踪指数分组=4",
          set(themes) == {"中证A500指数", "国证机器人产业指数", "恒生科技指数", "国证新能源电池指数"},
          str(set(themes)))
    check("机器人主题挂 020973", themes.get("国证机器人产业指数", {}).get("codes") == ["020973"])
    check("无跟踪标的的债基归宏观任务", macro and macro[0]["codes"] == ["110017"])
    covered = {c for j in jobs for c in j["codes"]}
    check("10只持仓全覆盖", len(covered) == 10)


def t8_generalization():
    print("[T8] 泛化用例：陌生用户（A股股票+积存金）")
    import validators as V
    H = {"asof": "2026-06-23", "period": "2026-06",
         "accounts": {"a": {"broker": "同花顺", "type": "cash", "ccy": "CNY"}},
         "positions": [
             {"acct": "a", "type": "stock", "market": "sh", "code": "600519", "name": "贵州茅台",
              "shares": 100, "cost_px": 1500.0},
             {"acct": "a", "type": "gold", "name": "招行积存金", "grams": 50,
              "screenshot": {"cost_per_gram": 720.0}}],
         "excluded": []}
    M = {"period": "2026-06", "d_start": "2026-05-29", "d_end": "2026-06-30",
         "funds": {}, "resolution": [], "flags": [],
         "stocks": {"600519": {"name": "贵州茅台", "market": "sh", "source": "em",
                    "close": [["2026-05-29", 1400.0], ["2026-06-30", 1470.0]],
                    "dividend_flag": False}},
         "benchmarks": {"SSE": {"name": "上证指数", "close": [["2026-05-29", 4068.57], ["2026-06-30", 4094.40]]}},
         "fx": {"close": [["2026-05-29", 0.8703], ["2026-06-30", 0.8686]], "source": "em"}}
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "01_holdings.json"), "w", encoding="utf-8") as f:
            json.dump(H, f, ensure_ascii=False)
        with open(os.path.join(td, "02_market.json"), "w", encoding="utf-8") as f:
            json.dump(M, f, ensure_ascii=False)
        ok, issues = V.validate_holdings(os.path.join(td, "01_holdings.json"))
        check("陌生持仓通过校验（黄金仅WARN不拦截）",
              ok and any(i.startswith("WARN:") and "gold" in i for i in issues), str(issues))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "s2_compute_returns.py"), td],
                           capture_output=True, text=True)
        check("S2 处理陌生持仓退出码=0", r.returncode == 0, r.stdout[-200:] + r.stderr[-200:])
        with open(os.path.join(td, "03_returns.json"), encoding="utf-8") as f:
            R = json.load(f)
        check("A股股票正常计价 +5.00%",
              len(R["holdings"]) == 1 and approx(R["holdings"][0]["ret_m"], 0.05, 1e-6))
        check("A股为CNY桶、无汇率折算",
              R["holdings"][0]["ccy"] == "CNY" and approx(R["summary"]["total_pnl_m_cny"], 7000, 0.01))
        check("积存金自动列入未纳入", len(R["excluded_auto"]) == 1 and "积存金" in R["excluded_auto"][0]["desc"])
        ok2, issues2 = V.validate_returns(os.path.join(td, "03_returns.json"),
                                          os.path.join(td, "01_holdings.json"))
        check("returns 校验闭合（持仓+未纳入=总数）", ok2, str(issues2[:3]))


def smoke():
    print("[SMOKE] 在线数据源冒烟")
    import lib
    try:
        rows = lib.fund_nav("110017", min_rows=15, max_pages=1)
        check("基金净值源可用", len(rows) > 10)
    except Exception as e:
        check("基金净值源可用", False, str(e))
    try:
        kf = lib.kline_full("116.00700", "20260601", "20260707")
        check(f"日K源可用({kf['source']})", len(kf["rows"]) > 5)
    except Exception as e:
        check("日K源可用", False, str(e))
    try:
        fx = lib.fx_series("120.HKDCNYC", "20260601", "20260707")
        check(f"汇率源可用({fx['source']})", len(fx["rows"]) > 3)
    except Exception as e:
        check("汇率源可用", False, str(e))


if __name__ == "__main__":
    t1_parsers()
    t2_fit()
    t2b_candidates()
    t3_returns()
    t4_validators()
    t5_build()
    t6_research_fixtures()
    t7_planner()
    t8_generalization()
    if "--smoke" in sys.argv:
        smoke()
    print(f"\n结果: {PASS} 通过, {len(FAIL)} 失败")
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
        sys.exit(1)
    print("ALL PASS ✅")
