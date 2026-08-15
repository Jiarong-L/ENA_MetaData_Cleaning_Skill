# 三类 conflict_projects.csv 冲突类型说明

本文记录三个维度（country / date / host）的 `*_conflict_projects.csv` 项目级冲突文件中的
**冲突类型字段**及其**对应含义**。所有数字均取自 `.tmp/` 下对应 CSV（生成脚本见各维度说明）。

> 总前提：这些"冲突"全部来自 **infer（项目级推断）与原表字段不一致**，而非原表自身矛盾；
> country/date/host 三个维度的真实冲突 100% 可追溯为 infer 推断错误（原表为权威来源）。

---

## 总览

| 维度 | 文件 | 项目数 | 冲突类型字段 | 冲突类型枚举 |
| --- | --- | --- | --- | --- |
| Country（国家） | `country.realconflict_projects.csv` | 217 | `conflict_type` | `fully_disjoint` / `introduced_unknown` / `incomplete_subset` |
| Date（采集日期） | `date.conflict_projects.csv` | 11,735 | `conflict_shapes` | `denial` / `genuine_year` |
| Host（宿主） | `host.realconflict_projects.csv` | 129 | `conflict_concept_pair` | 物种↔生境概念错配对（45 种，见下表） |

---

## 1. Country — `country.realconflict_projects.csv`

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

## 2. Date — `date.conflict_projects.csv`

判定逻辑（`_date_conflict_proj_report.py` / `_date_genuine_proj_report.py`）：
比对轴为 **collection_date（原采集日）↔ infer_value（推断采集日）**，`first_public`（发文年）单独处理、不参与比对。

| 冲突形态 `conflict_shapes` | 项目数 | 占 11,735 | 冲突来源 `conflict_from` | 对应了什么 |
| --- | --- | --- | --- | --- |
| `denial` | 11,396 | 97.1% | 全部 LLM（11,396） | **否认型冲突**：ENA 原表已有 collection_date（采集日），infer 却判 `NotDate`（声称"无日期信号"）。infer 只看 study/文献文本、未利用 ENA 自带结构字段。 |
| `genuine_year` | 339 | 2.9% | LLM 238 / rule 101 | **真年份冲突**：collection_date 年 与 infer 年 无交集（infer 从文本幻觉出非采样年，如历史事件年、引物文献引用年、仪器型号年、发表/期刊年）。 |

- 合计 `conflict_from`：LLM 11,634 / rule 101。
- 说明：`genuine_year` 的更严格子集单独存于 `date.genuine_conflict_projects.csv`（339 行）；
  两个文件的关系为 `conflict_projects.csv`（全量 11,735）⊇ `genuine_conflict_projects.csv`（339）。
- 结论：date 维度"原 collection_date 字段全面优于 infer"，不存在"ENA 错、infer 对"。

---

## 3. Host — `host.realconflict_projects.csv`

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
