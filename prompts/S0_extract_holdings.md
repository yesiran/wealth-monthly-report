# S0 持仓识别（通用：任何券商/银行/理财 App 的截图）

你在月报流水线的 S0 步骤。任务：把 `{PERIOD_DIR}/00_input/` 里的持仓截图识别成结构化 JSON。截图可能来自任何 App（富途、同花顺、招行、蚂蚁财富、天天基金、老虎、华泰……），版式各不相同——**不要依赖对某个 App 的记忆，只按下面的通用规则提取**。

## 核心原则：一切归结为「标的 + 份额」

后续所有价格数据都由代码去行情源抓取，你**不需要也不应该**提供任何行情价格判断。你的唯一使命是让每个持仓能被下游定价：

- **份额直接可见的**（股票的股数、基金的份额、黄金的克数）：照抄。
- **份额不可见、只有金额的**（多数基金页只显示持仓金额）：把「持仓金额、昨日收益、持仓收益」三个数字原样抄下来——下游代码会用它们数值反推份额并验证基金身份。**这三个数字是指纹，一个都别丢，有几个抄几个。**

## 操作步骤

1. Read 逐张读取 `{PERIOD_DIR}/00_input/` 下全部图片。
2. Read `{PREV_HOLDINGS}` 作为格式模板（可能是上一期持仓文件，也可能是默认模板）：benchmarks、fx_secid、excluded 沿用其值。
3. 写出 `{PERIOD_DIR}/01_holdings.json`。

## 输出 schema

- `asof`: 截图日期（YYYY-MM-DD，从截图状态栏/页面推断；多张截图日期不同取各自账户标注，整体取最主要的一天）
- `period`: "{PERIOD}"
- `accounts`: 每个账户一项，键名自拟（如 futu/cmb/ths），值 {broker:"App名", type:"margin|cash|fund|bank", ccy:"主币种", 以及截图可见的 market_value / net_assets / pnl_total（没有就不写）}
- `positions[]` 按资产类型：
  - 股票: `{acct, type:"stock", market:"hk|sh|sz|us", code:"字符串", name, shares, cost_px, screenshot:{px, value, pnl_total}}`（market 从代码规则和 App 语境判断：5位数字=hk，6开头=sh，0/3开头=sz，字母=us）
  - 基金: `{acct, type:"fund", code:6位字符串或null, name_display:"截图完整名称一字不差", screenshot:{amount, pnl_yday, pnl_total}}`
  - 黄金/积存金: `{acct, type:"gold", name, grams, cost_per_gram, screenshot:{...可见数字}}`
  - 看不懂/理财/其他: `{acct, type:"other", name, screenshot:{...可见数字}}`——**如实记录，不要硬塞进上面的类型**；系统会自动把暂不支持定价的资产列入报告的「未纳入」部分
- `benchmarks` / `fx_secid` / `excluded`: 沿用上期；无上期时用默认（A500/上证/恒指/恒生科技 + 120.HKDCNYC）

## 硬性规则

1. **数字一字不差照抄截图**，含小数位；绝不四舍五入、绝不推算、绝不脑补被遮挡的数字。
2. **自我对账后交卷**：账户页若显示总盈亏/总市值，各持仓相应数字之和必须对得上（±1）；股票 shares×现价 ≈ 市值。对不上=你读错了，重读。
3. 基金代码截图上通常没有：**填 null，不许猜**。基金名称必须一字不差（全称/简称、A/C 类字母都影响下游身份拟合）。
4. 任何不确定（模糊、遮挡、字段看不懂）：JSON 里给最优读数，同时写入 `{PERIOD_DIR}/05_notes/s0_report.md` 列明疑点。
5. 同一标的出现在多张截图（重复截图）只录一次；上期有、本期截图没有的持仓不录，并在 s0_report.md 说明。

完成后只输出一行：`S0 done: N 只持仓（股票a/基金b/其他c）, asof=YYYY-MM-DD, 疑点 M 个`。
