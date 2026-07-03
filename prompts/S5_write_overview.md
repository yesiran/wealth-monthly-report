# S5b 总览撰写（在全部标的叙事完成后执行）

你在月报流水线的 S5b 步骤，撰写本期（{PERIOD}）报告的封面与总览内容。

## 先读（Read 工具）

1. `tests/baseline_2026-06/06_narrative/overview.json` —— **黄金范例**，字段与颗粒度全部对齐。
2. `{PERIOD_DIR}/06_narrative/` 下全部标的叙事 JSON（你刚写完的）。
3. `{PERIOD_DIR}/03_returns.json` 与 `{PERIOD_DIR}/06_narrative/_tokens.txt`。
4. `{PERIOD_DIR}/05_review.json`（若存在）—— 上期预判复盘结果，速览里要提命中率。

## 写出 `{PERIOD_DIR}/06_narrative/overview.json`

- `publish_date`: "{TODAY}"
- `theme_title`: 4-8 字的本月主题（中文意象，像杂志封面标题，如「东边日出西边雨」）。
- `cover_lead`: 100-160 字导语：本月市场故事 + 组合结果 + 一句展望。数字用 {{token}}。
- `cover_stat4_note` / `cashflow_note` / `table_note`: 参照范例，按本期实际情况写（现金流如股息到账；无则 value 写 "—"）。
- `bench_order`: 沿用 ["A500","SSE","HSI","HSTECH"]。
- `brief_bullets`: 5-6 条本月速览，第一条必须是组合整体（{{sum.port_ret_m}} 等），随后是最大拖累/最大贡献/特殊事件/股息与除净/风险提示；若有 05_review.json，加一条「上期预判 N 中 M」。
- `checkup`: 恰好 4 条组合体检 {title, html}——集中度、杠杆、本月行为模式（新买入/调仓）、深套仓位或其他本月最值得点破的结构问题。要基于 returns.json 的真实权重与数字（用 token）。
- `calendar`: ≥10 行未来30-60天观察日历，汇总各标的叙事里的催化剂：{date, event, star, tags:[标的简称], note}。日期具体、去重、按时间排序，star 标最重要的 4-6 个。
- `methodology_extra`: 2-4 条本期特有的口径说明（截图日期与调仓假设、新标的的身份确认、股息处理、数据源降级说明等——查看 02_market.json 的 flags）。

## 硬性规则

同叙事步骤：token 数字、说人话、有立场。theme_title 不许用「震荡」「分化」这类万金油词汇单独成题。

完成后只输出一行：`S5b done: 主题「XXX」`。
