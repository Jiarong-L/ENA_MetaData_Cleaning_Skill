# 三类 conflict_projects.csv 冲突类型说明

本文记录三个维度（country / date / host）的 `*_conflict_projects.csv` 项目级冲突文件中的
**冲突类型字段**及其**对应含义**。所有数字均取自 `.tmp/` 下对应 CSV（生成脚本见各维度说明）。

> 总前提：这些"冲突"全部来自 **infer（项目级推断）与原表字段不一致**，而非原表自身矛盾；
> country/date/host 三个维度的真实冲突 100% 可追溯为 infer 推断错误（原表为权威来源）。

---

## 总览

| 维度 | 文件 | 冲突项目数（/重合项目数） | 冲突类型字段 | 冲突类型枚举 |
| --- | --- | --- | --- | --- |
| Country（国家） | `tmp.country.realconflict_projects.csv` | 217（/12,733） | `conflict_type` | `fully_disjoint` / `introduced_unknown` / `incomplete_subset` |
| Date（采集日期） | `tmp.date.genuine_conflict_projects.csv` | 271（/2,210） | `conflict_side` + `misjudge_source` | `orig_before_interval` / `orig_after_interval`（含 both）× `llm` / `rule` |
| Host（宿主） | `tmp.host.realconflict_projects.csv` | 129（/3,983） | `conflict_concept_pair` | 物种↔生境概念错配对（45 种，见下表） |

> 列「冲突项目数（/重合项目数）」：`冲突项目数` 即各 `*_conflict_projects.csv` 的项目数；`重合项目数` = 该项目下**至少 1 条 run 同时有 infer_value 与原表字段有效值**的项目总数（项目级，由对应 `*.filtered.csv` 统计）。

---

## 1. Country — `tmp.country.realconflict_projects.csv`

判定逻辑（`_report_67.py`）：对每项目聚合"原表国家集合 O"与"infer 国家集合 I"，
按集合关系分类。香港/澳门/台湾→中国、波多黎各/关岛→美国 已做语义归一化。

| 冲突类型 | 项目数 | 占 217 | 对应了什么 |
| --- | --- | --- | --- |
| `fully_disjoint` | 161 | 74.2% | **强推断错误**：infer 引入的国家在原表所有 run 中完全不存在（I ∩ O = ∅）。infer 把整个项目的国家判成了原表根本没有的国家（如把多国合作项目误归为单一国家）。 |
| `introduced_unknown` | 4 | 1.8% | **引入错误国家**：infer 与原表国家有交集，但额外引入了原表没有的国家（仍带部分正确，但掺入了错误国家）。 |
| `incomplete_subset` | 52 | 24.0% | **推断过窄（非真矛盾）**：infer 国家 ⊆ 原表国家，只是只抓到原表中的部分国家（漏了原表有的其他国家）。属"保守/不完整"，不算真正矛盾。 |

- 误判来源（infer 侧）：`infer_method` 含 `llm_agent` / `rule_place`（地名→国家）/ `rule_demonym`（形容词→国家）；
  典型误判如 KEGG "Kyoto"→Japan、"four Danish WWTPs"→Denmark、文献小镇→Italy、"American Indian"→India/US。
- 说明：`fully_disjoint`（161）+ `introduced_unknown`（4）= **165 个"引入原表不存在国家"的强错项目**，是应优先回查 `final_country.jsonl` 修正的对象。

---

## 2. Date — `tmp.date.genuine_conflict_projects.csv`

> **方法论变更（重要）**：早期版本把 date 冲突拆成 `denial`（ENA 有日期、infer 判 `NotDate`，11,396 项目）与 `genuine_year`（真年份冲突，339 项目）。
> 自 `_filter_notdate.py` 把**全部 `NotDate` 推断值清空**后，`denial` 类已不再构成冲突，date 维度只剩 **genuine year conflict（真年份冲突）**。
> 本节的 271 项目 / 6,154 行即当前口径结果，由 `_analyze_date_v2.py` 生成（`tmp.date.genuine_conflict_projects.csv` + `tmp.date.genconflict_rows.csv`）。

判定逻辑：比对轴为 **collection_date（原采集日，取其中的年份集合）↔ infer 年区间 `[infer_lo, infer_hi]`**（由 infer 值/区间解析）。
当 **原年份集合 与 infer 年区间无交集** 时记为真年份冲突；`first_public`（发文年）单独处理、不参与比对。

### 2.1 冲突类型一：方向 `conflict_side`（年份偏早还是偏晚）

| 冲突方向 `conflict_side` | 项目数 | 对应了什么 |
| --- | --- | --- |
| `orig_before_interval` | 138 | **infer 把年份定得偏晚（高估）**：原表采集年整体早于 infer 年区间（ENA 实际更早，infer 抽到了更晚的年份，如论文发表年/项目启动年）。 |
| `orig_after_interval` | 126 | **infer 把年份定得偏早（低估）**：原表采集年整体晚于 infer 年区间（ENA 实际更晚，infer 抽到了更早的年份，如历史事件年/被引文献年）。 |
| `orig_before_interval\|orig_after_interval` | 7 | 同一项目内兼有偏早与偏晚的行（方向混杂）。 |

行级（`tmp.date.genconflict_rows.csv`，6,154 行）对应 `before` 1,925 / `after` 4,229 —— **约 69% 的真年份冲突是 infer 把年份估得偏早**（infer 落在 ENA 实际采集年之前）。

### 2.2 冲突类型二：误判来源 `misjudge_source`

| 误判来源 `misjudge_source` | 项目数 | 占 271 | 对应了什么 |
| --- | --- | --- | --- |
| `rule` | 73 | 26.9% | **规则/文献抽取错误**：infer 方法为 `literature\|rule_date`（40）或 `study_meta\|rule_date`（21，含少量组合）。即从 EPMC 论文或 study 描述里用规则抽出一个"日期"，却与 ENA 的 `collection_date` 矛盾（多为论文发表年/项目年 ≠ 采样年）。 |
| `llm` | 198 | 73.1% | **LLM 直接臆测年份**：infer 方法为 `llm_agent`（184，含组合）。LLM 读文本后断言的年份不在 ENA 采集年集合内（最常见为偏早一年，如把 2016 采的样本估成 2015）。 |

- 行级来源分布（`infer_method`）：`llm_agent` 3,092 行 / `rule_date` 3,062 行，二分天下。
- 结论：date 真年份冲突 **100% 来自 infer 端**（rule 抽错文本年 或 LLM 估错年），不存在"ENA 错、infer 对"。

### 2.3 示例

- **rule 偏晚**（orig_before_interval）：`PRJNA1150505` infer=`2020` vs 原 `2016`（study 文本年 ≠ 采样年）；`PRJEB66439` infer=`2019` vs 原 `2020`（论文年早一年）。
- **llm 偏早**（orig_after_interval）：`PRJEB53055` infer=`2022` vs 原 `2022/2023/2026`（LLM 只抓到最早年，漏掉 2026）；`PRJEB34633` infer=`2015` vs 原 `2016+`（估早一年）。

### 2.4 补充：原表采集年跨度与脏日期分析（`tmp.date.span_projects.csv`，430 项目）

与上述"冲突"不同，这份是**原表自身年份结构**的体检（非 infer 冲突）。对原 `collection_date` 按年跨度分类：

| 类别 `category` | 项目数 | 对应了什么 |
| --- | --- | --- |
| `continuous` | 225 | 连续多年监测 / 逐年积累的菌株库（年份连续，跨度由研究设计决定）。 |
| `mid_long` | 81 | 跨度 10–39 年、非历史标本的中长期生态/临床收集。 |
| `other` | 103 | 跨世纪但非典型双峰的杂项长跨度。 |
| `archival` | 21 | 历史标本 + 现代重测序双峰（一端 1900s–1950s 馆藏，一端 2005+ 重测序），如 `PRJEB42014` 1842→2016、`PRJNA857715` 1905→2021。 |

- **脏日期 outlier（应视为缺失，非真实跨度）**：`outlier_flag` 标记 9 个项目年份被离群点撑高；`has_invalid_orig=Y` 的 **3 个**为典型脏值——
  - `PRJEB33603`：含 `1900-01-00`（日=00 无效占位符）→ 原跨度从 118 年纠正为 5 年（2013→2018）；
  - `PRJEB6997`：含 `2099` 等未来年占位符 → 跨度被虚假撑到 87 年；
  - `PRJEB63570`：含 `2027` 未来年（1 run）。
  全表另有 74 个 run 的采集年 > 2026（2027→2099），均属未来占位符。

---

## 3. Host — `tmp.host.realconflict_projects.csv`

判定逻辑（`_host_realconflict.py`）：host 本质是**物种名**（orig `host`）vs **生境/生物群系描述**
（infer `host`，如 `human gut metagenome`），两套不同本体。先把两侧归一化到统一 host 概念
（词边界正则避免 `tract→rat`、`coral→oral` 子串误判），逐行判定后聚合到项目。

项目级 `conflict_concept_pair` 字段记录"orig 概念 → infer 概念"的错配方向（共 45 种）。

| 冲突类型 / 概念对 `conflict_concept_pair` | 项目数 | 对应了什么 |
| --- | --- | --- |
| `mouse → human` | 39 | orig 为小鼠（实验/野生），infer 过度归为 human gut —— 最常见错配。 |
| `soil → plant` | 14 | orig 为土壤环境，infer 归为植物相关 —— 生境粒度差异。 |
| `human → mouse` | 12 | 反向：orig 为人，infer 归为鼠。 |
| `plant → soil` | 5 | 反向生境错配。 |
| `sheep → human` | 4 | 反刍动物（羊）被归为人类。 |
| `mouse → rat` | 3 | 鼠类内部混淆（小鼠↔大鼠）。 |
| `freshwater → fish` | 3 | 淡水环境被归为鱼类宿主。 |
| `rat → human` | 2 | 大鼠被归为人类。 |
| `human → primate` | 2 | 人被归为灵长类（粒度/分类差异）。 |
| `bovine → human` | 2 | 牛被归为人类。 |
| `horse → wildlife` | 2 | 马被归为野生动物（描述粒度差异）。 |
| `pig → human` | 2 | 猪被归为人类。 |
| 其余 33 种零散对 | 39 | 其它动物/生境错配（如 `pig→{human,bovine}`、`yak→bovine` 等），合计 39 项目。 |

- **总项目数**：129（= 真实冲突项目数；行级 4,630 行真实冲突）。
- **误判来源 `misjudge_source`**：LLM **124** / rule **5**（rule 含 PRJEB42019、PRJNA1010707、PRJNA1092431 等）。
- 行级三大类（供参照）：写法不一 `agree` 213,360（86.7%）/ 真实冲突 `conflict` 4,630（1.9%，即上表 129 项目）/ 不确定 `uncertain` 28,130（11.4%，多为病毒/未覆盖植物物种，已正确排除出真实冲突）。
- 结论：host 真实冲突几乎全是**物种级错配**（infer 把项目整体过度归为 human/mouse gut 等），100% 来自 infer 错误。

---

## 附注：与论文评价的关联

country 维度曾进一步交叉 `agent_paper_verdicts.jsonl` 的论文主题评价（`"aligned"` 字段）：
- 217 个 country 真矛盾项目中，**113 个**有被评价论文（共 150 条 verdict），其中 `aligned:false` **31** 篇；
- 其中 `fully_disjoint`（强错）161 项目中，**70 个**有评价（88 条 verdict），`aligned:false` **18** 篇。
- 即约 58% 的"论文未对齐"集中在最严重的一类（`fully_disjoint`）错误上。
