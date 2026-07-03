#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月报流水线驱动器。

用法:
  python3 run.py --period 2026-07                 # 全流程（s0→s8，含两个人工确认点）
  python3 run.py --period 2026-07 --steps s1,s2   # 只跑指定步骤
  python3 run.py --period 2026-07 --dry-run       # 打印将执行的 LLM 命令，不真调
  python3 run.py --period 2026-07 --yes           # 跳过人工确认点
  python3 run.py --period 2026-07 --skip-tests    # 跳过启动前回归测试（不建议）

步骤: s0 持仓识别(LLM) → s1 行情(脚本) → s2 收益(脚本) → s3 预判复盘(LLM)
      → s4 研究(LLM×9) → s5 叙事(LLM×N+1) → s6 出版(脚本) → s7 质检(LLM) → s8 档案回写(LLM)
每步产物写入 <period>/ 目录，步骤幂等：产物已存在且校验通过则跳过（--force 重跑）。
"""
import argparse, json, os, re, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import validators as V  # noqa: E402
from lib import get_logger  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8"))
TODAY = datetime.date.today().isoformat()
logger = get_logger("run")


def log(msg):
    logger.info(msg)


def die(msg):
    logger.error(f"中止: {msg}")
    sys.exit(1)


def checkpoint(name, summary, args):
    if args.yes or name not in CFG.get("checkpoints", []):
        return
    print(f"\n===== 人工确认点 [{name}] =====\n{summary}")
    if not sys.stdin.isatty():
        log("非交互环境，自动继续（用 --yes 显式声明可去掉本提示）")
        return
    ans = input("确认继续？[y/N] ").strip().lower()
    if ans != "y":
        die("用户在确认点停止")


def run_py(script, *sargs):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *sargs],
                       cwd=ROOT)
    return r.returncode


def llm_call(prompt_file, variables, args, label):
    """headless 调用 claude；prompt 文件内容做 {VAR} 替换后作为 -p 参数。"""
    with open(os.path.join(ROOT, "prompts", prompt_file), encoding="utf-8") as f:
        prompt = f.read()
    for k, v in variables.items():
        prompt = prompt.replace("{" + k + "}", str(v))
    cmd = ["claude", "-p", prompt,
           "--model", CFG["model"],
           "--permission-mode", CFG["permission_mode"],
           "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]
    if args.dry_run:
        log(f"[dry-run] {label}: claude -p <{prompt_file}, {len(prompt)}字> --model {CFG['model']}")
        return True
    log(f"LLM {label} ({prompt_file}) ...")
    logdir = os.path.join(ROOT, args.period, "05_notes")
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, f"llm_{label}.log"), "w", encoding="utf-8") as lf:
        r = subprocess.run(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT,
                           timeout=CFG.get("llm_timeout_sec", 1800))
    if r.returncode != 0:
        log(f"⚠ LLM {label} 退出码 {r.returncode}（查看 05_notes/llm_{label}.log）")
    return r.returncode == 0


def validated(step_label, fn, *fargs, retry_ctx=None, args=None):
    ok, issues = fn(*fargs)
    if ok:
        log(f"✓ 校验通过: {step_label}")
        return True
    log(f"✗ 校验失败: {step_label}")
    for i in issues[:8]:
        log(f"    - {i}")
    if retry_ctx and args and not args.dry_run:
        log(f"  重试一次（附带校验问题）...")
        prompt_file, variables, label = retry_ctx
        variables = dict(variables)
        variables["RETRY_NOTE"] = "；".join(issues[:6])
        # 在 prompt 末尾追加修正指令
        with open(os.path.join(ROOT, "prompts", prompt_file), encoding="utf-8") as f:
            base = f.read()
        for k, v in variables.items():
            base = base.replace("{" + k + "}", str(v))
        base += f"\n\n## 上次输出未通过校验，修正后重写\n问题：{variables['RETRY_NOTE']}\n"
        cmd = ["claude", "-p", base, "--model", CFG["model"],
               "--permission-mode", CFG["permission_mode"],
               "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]
        subprocess.run(cmd, cwd=ROOT, capture_output=True,
                       timeout=CFG.get("llm_timeout_sec", 1800))
        ok2, issues2 = fn(*fargs)
        if ok2:
            log(f"✓ 重试后通过: {step_label}")
            return True
        log(f"✗ 重试仍失败: {issues2[:5]}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--steps", default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()

    P = args.period
    PD = os.path.join(ROOT, P)
    os.makedirs(os.path.join(PD, "00_input"), exist_ok=True)
    for sub in ("04_research", "05_notes", "06_narrative"):
        os.makedirs(os.path.join(PD, sub), exist_ok=True)
    steps = (["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"]
             if args.steps == "all" else args.steps.split(","))
    fp = lambda name: os.path.join(PD, name)
    done = lambda name: os.path.exists(fp(name)) and not args.force

    # ---- 启动前回归测试 ----
    if not args.skip_tests:
        log("启动前回归测试 ...")
        if subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_tests.py")],
                          cwd=ROOT, capture_output=True).returncode != 0:
            die("回归测试未通过——先修复 scripts/ 再出报告（python3 tests/run_tests.py 查看明细）")
        log("回归测试通过 ✅")

    common = {"PERIOD": P, "PERIOD_DIR": P, "TODAY": TODAY}

    # ---- S0 持仓识别 ----
    if "s0" in steps and not done("01_holdings.json"):
        imgs = [x for x in os.listdir(fp("00_input"))
                if x.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic"))]
        if not imgs:
            inp = os.path.abspath(fp("00_input"))
            log(f"本期目录已就绪：{P}/（首次运行自动创建，无需手动建文件夹）")
            print(f"""
┌─────────────────── 下一步 ───────────────────
│ 1. 把本期的持仓截图放进这个文件夹（已为你打开）：
│    {inp}
│    支持 jpg/png 等，任意券商/银行/理财 App，几张都行。
│ 2. 放好后，重新运行同一条命令：
│    python3 run.py --period {P}
│    流程会自动继续：识图（等你确认）→ 行情 → 计算
│    → 研究 → 成稿 → 出 PDF（再等你终审）。
└──────────────────────────────────────────────""")
            subprocess.run(["open", inp], check=False)  # macOS 自动打开文件夹
            return
        # 上一期 holdings 作为格式模板；没有上期则用默认模板
        prevs = sorted(d for d in os.listdir(ROOT)
                       if re.match(r"^\d{4}-\d{2}$", d) and d < P
                       and os.path.exists(os.path.join(ROOT, d, "01_holdings.json")))
        v = dict(common, PREV_HOLDINGS=(f"{prevs[-1]}/01_holdings.json" if prevs
                                        else "config/holdings_template.json"))
        llm_call("S0_extract_holdings.md", v, args, "s0")
        if not args.dry_run:
            if not validated("01_holdings.json", V.validate_holdings, fp("01_holdings.json"),
                             retry_ctx=("S0_extract_holdings.md", v, "s0"), args=args):
                die("S0 持仓识别未通过校验")
            with open(fp("01_holdings.json"), encoding="utf-8") as f:
                H = json.load(f)
            checkpoint("s0", f"识别出 {len(H['positions'])} 只持仓 (asof={H['asof']})，"
                             f"请人工核对 {P}/01_holdings.json 与截图是否一致", args)

    # ---- S1 行情 ----
    if "s1" in steps and not done("02_market.json"):
        if run_py("s1_fetch_market.py", PD) not in (0,):
            log("⚠ S1 返回非零（可能有待处理 flag）")
        ok, issues = V.validate_market(fp("02_market.json"))
        if not ok:
            die(f"S1 校验失败: {issues}")
        log("✓ S1 行情采集完成")

    # ---- S2 收益 ----
    if "s2" in steps and not done("03_returns.json"):
        if run_py("s2_compute_returns.py", PD) != 0:
            die("S2 计算出错（查看输出）")
        ok, issues = V.validate_returns(fp("03_returns.json"), fp("01_holdings.json"))
        if not ok:
            die(f"S2 校验失败: {issues}")
        log("✓ S2 收益计算完成")

    # ---- token 表（S5 的词表） ----
    R = None
    if os.path.exists(fp("03_returns.json")):
        from s6_build_html import build_token_table
        with open(fp("03_returns.json"), encoding="utf-8") as f:
            R = json.load(f)
        T = build_token_table(R)
        with open(fp("06_narrative/_tokens.txt"), "w", encoding="utf-8") as f:
            f.write("# 本期可用占位符（正文写 {{token}}，出版时自动替换为右侧值）\n")
            for k, vv in sorted(T.items()):
                f.write(f"{{{{{k}}}}} = {vv}\n")

    if R is None and any(s in steps for s in ("s3", "s4", "s5")):
        die("s3/s4/s5 需要 03_returns.json，请先跑 s1,s2")

    # ---- S3 预判复盘 ----
    if "s3" in steps and not done("05_review.json"):
        import glob as _g
        has_pending = any("⏳" in open(x, encoding="utf-8").read()
                          for x in _g.glob(os.path.join(ROOT, "dossiers", "*.md")))
        if has_pending:
            v = dict(common, D_START=R["d_start"], D_END=R["d_end"])
            llm_call("S3_review_predictions.md", v, args, "s3")
            if not args.dry_run and not os.path.exists(fp("05_review.json")):
                log("⚠ S3 未产出 05_review.json，报告将不含复盘节")
        else:
            log("S3 跳过：档案中无待复盘预判")

    # ---- 研究任务自动规划（纯代码：个股一任务、基金按跟踪指数分组、主动/债基归宏观） ----
    plan = None
    if any(s in steps for s in ("s4", "s5")):
        plan_fp = fp("04_research/_plan.json")
        if not os.path.exists(plan_fp) or args.force:
            if run_py("plan_research.py", PD) != 0:
                die("研究任务规划失败")
        with open(plan_fp, encoding="utf-8") as f:
            plan = json.load(f)
        log(f"研究规划: {len(plan)} 个任务")

    # ---- S4 研究（独立任务，并行执行） ----
    if "s4" in steps:
        from concurrent.futures import ThreadPoolExecutor
        conc = CFG.get("llm_concurrency", 4)
        code2name = {h["code"]: h["name"] for h in R["holdings"]}
        todo = []
        for job in plan:
            live = [c for c in job["codes"] if c in code2name]
            if not live:
                continue
            note = fp(f"04_research/研究_{job['id']}.md")
            if os.path.exists(note) and not args.force:
                continue
            v = dict(common, NAME=job["name"], JOB_ID=job["id"],
                     D_START=R["d_start"], D_END=R["d_end"],
                     CODE=live[0],
                     FUND_LIST="、".join(f"{code2name[c]}({c})" for c in live),
                     DOSSIER_LIST="、".join(f"dossiers/{c}.md" for c in live))
            tpl = "S4_research_stock.md" if job["kind"] == "stock" else "S4_research_theme.md"
            todo.append((job["id"], tpl, v, note))

        def run_s4(item):
            jid, tpl, v, note = item
            llm_call(tpl, v, args, f"s4_{jid}")
            if args.dry_run:
                return True
            return validated(f"研究_{jid}", V.validate_research, note,
                             retry_ctx=(tpl, v, f"s4_{jid}"), args=args)

        if todo:
            log(f"S4 研究：{len(todo)} 个任务，{conc} 路并行 ...")
            with ThreadPoolExecutor(max_workers=conc) as ex:
                oks = list(ex.map(run_s4, todo))
            if not all(oks):
                die("S4 有研究任务未通过校验（详见上方日志）")
        log("✓ S4 研究完成")

    # ---- S5 叙事（各标的独立，并行执行；总览在其后） ----
    if "s5" in steps:
        from concurrent.futures import ThreadPoolExecutor
        conc = CFG.get("llm_concurrency", 4)
        code2job = {}
        for job in plan:
            for c in job["codes"]:
                code2job[c] = job["id"]
        todo = []
        for h in R["holdings"]:
            out = fp(f"06_narrative/{h['code']}.json")
            if os.path.exists(out) and not args.force:
                continue
            v = dict(common, NAME=h["name"], CODE=h["code"],
                     RESEARCH_ID=code2job.get(h["code"], h["code"]))
            todo.append((h["code"], v, out))

        def run_s5(item):
            code, v, out = item
            llm_call("S5_write_narrative.md", v, args, f"s5_{code}")
            if args.dry_run:
                return True
            return validated(f"narrative {code}", V.validate_narrative,
                             out, fp("03_returns.json"),
                             retry_ctx=("S5_write_narrative.md", v, f"s5_{code}"), args=args)

        if todo:
            log(f"S5 叙事：{len(todo)} 个标的，{conc} 路并行 ...")
            with ThreadPoolExecutor(max_workers=conc) as ex:
                oks = list(ex.map(run_s5, todo))
            if not all(oks):
                die("S5 有叙事未通过校验（详见上方日志）")
        if not (os.path.exists(fp("06_narrative/overview.json")) and not args.force):
            llm_call("S5_write_overview.md", common, args, "s5_overview")
            if not args.dry_run:
                if not validated("overview", V.validate_overview,
                                 fp("06_narrative/overview.json"), fp("03_returns.json"),
                                 retry_ctx=("S5_write_overview.md", common, "s5_overview"), args=args):
                    die("S5b 总览未通过校验")
        log("✓ S5 叙事完成")

    # ---- S6 出版 ----
    if "s6" in steps:
        if run_py("s6_build_html.py", PD) != 0:
            die("S6 组装失败")
        ok, issues = V.validate_html(fp("07_report.html"), fp("03_returns.json"))
        if not ok:
            die(f"S6 HTML 校验失败: {issues}")
        env = dict(os.environ, NODE_PATH=CFG["puppeteer_node_path"])
        r = subprocess.run(["node", os.path.join(SCRIPTS, "topdf.js"),
                            fp("07_report.html"), fp("08_report.pdf")], env=env, cwd=ROOT)
        if r.returncode != 0:
            die("PDF 生成失败")
        log(f"✓ S6 出版完成: {P}/08_report.pdf")

    # ---- S7 质检 ----
    if "s7" in steps:
        llm_call("S7_qa_visual.md", common, args, "s7")
        if not args.dry_run:
            qfp = fp("05_notes/qa_report.json")
            if os.path.exists(qfp):
                with open(qfp, encoding="utf-8") as f:
                    qa = json.load(f)
                blockers = [i for i in qa.get("issues", []) if i.get("severity") == "blocker"]
                if blockers:
                    die(f"S7 质检发现 blocker：{blockers}（修复后重跑 s5/s6）")
                checkpoint("s7", f"质检通过（minor {len(qa.get('issues', []))} 个），"
                                 f"请翻阅 {P}/08_report.pdf 做最终确认", args)
            else:
                log("⚠ S7 未产出 qa_report.json，请人工翻阅 PDF")

    # ---- S8 档案回写 ----
    if "s8" in steps:
        llm_call("S8_update_dossiers.md", common, args, "s8")
        if not args.dry_run:
            import glob as _g
            n_updated = sum(1 for x in _g.glob(os.path.join(ROOT, "dossiers", "*.md"))
                            if f"### {P}" in open(x, encoding="utf-8").read())
            log(f"S8 档案回写：{n_updated} 份档案含 {P} 小节")
            if n_updated < len(R["holdings"]):
                log("⚠ 部分档案未更新，请检查 05_notes/llm_s8.log")

    log("流水线结束 🎉")


if __name__ == "__main__":
    main()
