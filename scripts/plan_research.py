#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究任务自动规划：01_holdings.json + 02_market.json -> <period>/04_research/_plan.json
规则（纯代码，不依赖任何写死的标的清单）：
- 每只可定价的股票 -> 一个个股研究任务（id=代码）
- 指数型基金 -> 按 S1 抓到的"跟踪标的"分组，同指数的基金共享一个主题研究任务
- 无跟踪标的的基金（主动/债券型）-> 归入"宏观与债市"兜底任务
用法: python3 plan_research.py <period_dir>
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import norm_position, get_logger

log = get_logger("plan")


def make_plan(H, M):
    jobs = []
    # 个股
    for p in H["positions"]:
        kind, _, _ = norm_position(p)
        if kind == "stock" and p.get("code") in M.get("stocks", {}):
            jobs.append({"id": p["code"], "kind": "stock",
                         "name": p["name"], "codes": [p["code"]]})
    # 基金按跟踪指数分组
    res = {r["display"]: r for r in M.get("resolution", []) if r.get("ok")}
    themes, macro = {}, []
    for p in H["positions"]:
        kind, _, _ = norm_position(p)
        if kind != "fund":
            continue
        r = res.get(p.get("name_display"))
        if not r:
            continue
        code = r["code"]
        track = (M["funds"][code].get("track") or "").strip()
        if track and "无跟踪标的" not in track and track not in ("--", "—", "无"):
            themes.setdefault(track, []).append(code)
        else:
            macro.append(code)
    for track, codes in sorted(themes.items()):
        tid = "t_" + re.sub(r"[^\w一-鿿]+", "", track)[:24]
        jobs.append({"id": tid, "kind": "theme", "track": track,
                     "name": f"{track}对应的板块/主题", "codes": codes})
    if macro:
        jobs.append({"id": "t_macro", "kind": "theme",
                     "name": "A股宏观与债券市场（主动管理型/债券基金视角）", "codes": macro})
    return jobs


def main(period_dir):
    with open(os.path.join(period_dir, "01_holdings.json"), encoding="utf-8") as f:
        H = json.load(f)
    with open(os.path.join(period_dir, "02_market.json"), encoding="utf-8") as f:
        M = json.load(f)
    jobs = make_plan(H, M)
    out = os.path.join(period_dir, "04_research", "_plan.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=1)
    log.info(f"===== 研究规划完成: {len(jobs)} 个任务 =====")
    for j in jobs:
        log.info(f"  [{j['kind']}] {j['id']}: {j['name']} <- {j['codes']}")
    covered = {c for j in jobs for c in j["codes"]}
    n_pos = len(H["positions"])
    if len(covered) < n_pos:
        log.warning(f"覆盖 {len(covered)}/{n_pos} 只持仓（未覆盖的为未定价/未解析标的）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
