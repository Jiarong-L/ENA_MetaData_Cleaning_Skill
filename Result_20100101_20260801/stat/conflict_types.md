# 三类 conflict_projects.csv 冲突类型说明

本文件只记录三个维度（country / date / host）的项目级冲突文件中的**冲突类型分布与含义**：

- Country：`tmp.country.genuine_conflict_projects.csv`（1,530 项目）
- Date：`tmp.date.genuine_conflict_projects.csv`（271 项目）
- Host：`tmp.host.realconflict_projects.csv`（129 项目）

> 总前提：这些"冲突"全部来自 **infer（项目级推断）与原表字段不一致**，而非原表自身矛盾；
> 三维度真实冲突 100% 可追溯为 infer 推断错误（原表为权威来源）。

---

## 总览

| 维度 | 文件 | 冲突项目数（/重合项目数） | 冲突类型字段 | 冲突类型枚举 |
| --- | --- | --- | --- | --- |
| Country | `tmp.country.genuine_conflict_projects.csv` | 1,530（/12,796） | `conflict_type` | `notcountry_kept` / `fully_disjoint` / `incomplete_subset` / `other` |
| Date | `tmp.date.genuine_conflict_projects.csv` | 271（/2,210） | `conflict_side` | `orig_before_interval` / `orig_after_interval`（含 both） |
| Host | `tmp.host.realconflict_projects.csv` | 129（/3,983） | `conflict_concept_pair` | 物种↔生境概念错配对（共 45 种） |

> `冲突项目数` = 各 `*_conflict_projects.csv` 的项目数；`重合项目数` = 该项目下**至少 1 条 run 同时有 infer_value 与原表字段有效值**的项目总数（country 12,796 / date 2,210 / host 3,983）。

---

## 1. Country — `tmp.country.genuine_conflict_projects.csv`

> 注：`final_country.jsonl` 中 `NotCountry:*` 值**只保留「海洋/公海」与「多国/全球聚合」两类**写入 `infer_value`，其余清空。因此 `notcountry_kept` 是保留决策所致，并非推断错误。

### 1.1 按 `conflict_type`

| 冲突类型 | 项目数 | 占 1,530 | 对应了什么 |
| --- | --- | --- | --- |
| `notcountry_kept` | 788 | 51.5% | 原表 `country` 含具体国名（或海域名），infer 保留为 海洋/公海/全球聚合（`NotCountry:*`）。语义上 infer 的「无单一国家」往往是正确答案（如 PRJEB42019 orig 含 atlantic ocean / north pacific ocean），**不属 misjudge**。 |
| `fully_disjoint` | 624 | 40.8% | **强推断错误**：infer 引入的国家/大区在原表所有 run 完全不存在（如 PRJEB40383 infer=Uganda 但 orig 全为 Malawi；PRJEB6070 Kyoto→Japan 但 orig 为 France/Germany）。最应回查 `final_country.jsonl` 修正。 |
| `incomplete_subset` | 116 | 7.6% | **推断过窄（非真矛盾）**：infer 国家 ⊆ 原表国家，只抓到原表部分国家（如 PRJEB32762 infer=Argentina 但项目主体为 US）。补全仍可用。 |
| `other` | 2 | 0.1% | 原表 `country` 为 `missing: sample group`/`missing: control sample` 等带后缀占位符，躲过空值判定但被 `norm()` 归空、分布为空、无法归类（假阳性冲突，共 11 run）。 |

### 1.2 按 `misjudge_source`（infer 端误判来源）

| 误判来源 | 项目数 | 占 1,530 |
| --- | --- | --- |
| `llm` | 1,259 | 82.2% |
| `rule` | 187 | 12.2% |
| `rule_place` | 50 | 3.3% |
| `rule_demonym` | 28 | 1.8% |
| `rule_open_ocean` | 6 | 0.4% |

- 真正需修正的强错 = `fully_disjoint`（624）+ `incomplete_subset`（116）+ `other`（2）= **742** 个；`notcountry_kept`（788）为保留决策、非误判、无需排除。

### 1.3 代表性示例

- `notcountry_kept`：`PRJNA656268`（infer=NotCountry:global ocean multi-region，orig 全为 indian/atlantic/pacific/southern ocean）、`PRJEB42019`（infer=NotCountry:global，orig 含 atlantic ocean / north pacific ocean）。
- `fully_disjoint`：`PRJEB40383`（Uganda vs Malawi，rule_place）；`PRJEB6070`（Kyoto→Japan vs France/Germany，rule_place）；`PRJEB17632`（asia vs Kazakhstan/Germany，rule，continent 非国家）。
- `incomplete_subset`：`PRJEB32762`（Argentina:Buenos Aires vs orig=US 1590/Argentina 908/UK 630，rule_place 只抓到首府）；`PRJEB5224`（China vs orig=Spain 318/Denmark 244/China 17，rule_demonym，「Chinese」误归）。
- `other`：`PRJNA1135464`（orig=`missing: sample group`×10，infer=atlantic）、`PRJDB16160`（orig=`missing: control sample`，infer=United States）。

---

## 2. Date — `tmp.date.genuine_conflict_projects.csv`

> 口径：自 `NotDate` 推断值全部清空后，date 仅剩 **genuine year conflict（真年份冲突）**——原采集年集合与 infer 年区间无交集。比对轴为 `collection_date` 年份集合 ↔ infer 年区间 `[infer_lo, infer_hi]`。

### 2.1 按 `conflict_side`（年份偏早还是偏晚）

| 冲突方向 | 项目数 | 占 271 | 对应了什么 |
| --- | --- | --- | --- |
| `orig_before_interval` | 138 | 50.9% | **infer 把年份定得偏晚（高估）**：原表采集年整体早于 infer 年区间（infer 抽到更晚的年份，如论文发表年/项目启动年）。 |
| `orig_after_interval` | 126 | 46.5% | **infer 把年份定得偏早（低估）**：原表采集年整体晚于 infer 年区间（infer 抽到更早的年份，如历史事件年/被引文献年）。 |
| `orig_before_interval\|orig_after_interval` | 7 | 2.6% | 同一项目内兼有偏早与偏晚（方向混杂）。 |

### 2.2 按 `misjudge_source`

| 误判来源 | 项目数 | 占 271 | 对应了什么 |
| --- | --- | --- | --- |
| `llm` | 198 | 73.1% | **LLM 直接臆测年份**（方法 `llm_agent`）：断言的年份不在 ENA 采集年集合内（最常见为偏早一年，如 2016 采的样本估成 2015）。 |
| `rule` | 73 | 26.9% | **规则/文献抽取错误**（方法 `literature\|rule_date` 或 `study_meta\|rule_date`）：从 EPMC 论文或 study 描述里抽出的"日期"与 `collection_date` 矛盾（多为论文发表年/项目年 ≠ 采样年）。 |

- 全部 271 个真年份冲突 **100% 来自 infer 端**（rule 抽错文本年 或 LLM 估错年），不存在"ENA 错、infer 对"。

### 2.3 示例

- **rule 偏晚**（orig_before_interval）：`PRJNA1150505`（infer=2020 vs 原 2016，study 文本年 ≠ 采样年）；`PRJEB66439`（infer=2019 vs 原 2020，论文年早一年）。
- **llm 偏早**（orig_after_interval）：`PRJEB53055`（infer=2022 vs 原 2022/2023/2026，LLM 只抓最早年、漏 2026）；`PRJEB34633`（infer=2015 vs 原 2016+，估早一年）。

---

## 3. Host — `tmp.host.realconflict_projects.csv`

> 注：host 本质是**物种名**（orig `host`）vs **生境/生物群系描述**（infer `host`，如 `human gut metagenome`），两套不同本体。

### 3.1 按 `conflict_concept_pair`（orig 概念 → infer 概念）

项目级共 **45 种**错配对。按项目数 Top 12：

| 概念错配 `conflict_concept_pair` | 项目数 | 对应了什么 |
| --- | --- | --- |
| `mouse → human` | 39 | orig 为小鼠，infer 过度归为 human gut —— 最常见错配。 |
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
| 其余 33 种零散对 | 39 | 其它动物/生境错配（如 `pig→{human,bovine}`、`yak→bovine`、`freshwater→marine` 等），合计 39 项目。 |

### 3.2 按 `misjudge_source`

- **LLM 124 / rule 5**（rule 含 PRJEB42019、PRJNA1010707、PRJNA1092431 等）。
- host 真实冲突几乎全是**物种级错配**（infer 把项目整体过度归为 human/mouse gut 等），**100% 来自 infer 错误**。
