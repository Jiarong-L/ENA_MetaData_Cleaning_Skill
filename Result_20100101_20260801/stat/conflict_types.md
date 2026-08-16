# 三类 conflict_projects.csv 冲突类型说明

本文件只记录三个维度（country / date / host）的项目级冲突文件中的**冲突类型分布与含义**：

- Country：`tmp.country.genuine_conflict_projects.csv`（1,388 项目）
- Date：`tmp.date.genuine_conflict_projects.csv`（339 项目）
- Host：`tmp.host.realconflict_projects.csv`（346 项目）

> 总前提：这些"冲突"全部来自 **infer（项目级推断）与原表字段不一致**，而非原表自身矛盾；
> 三维度真实冲突 100% 可追溯为 infer 推断错误（原表为权威来源）。

---

## 总览

| 维度 | 文件 | 冲突项目数（/重合项目数） | 冲突类型字段 | 冲突类型枚举 |
| --- | --- | --- | --- | --- |
| Country | `tmp.country.genuine_conflict_projects.csv` | 1,388（/12,652） | `conflict_type` | `notcountry_kept` / `fully_disjoint` / `incomplete_subset` / `other` |
| Date | `tmp.date.genuine_conflict_projects.csv` | 339（/2,326） | `conflict_side` | `orig_before_interval` / `orig_after_interval`（含 both） |
| Host | `tmp.host.realconflict_projects.csv` | 346（/17,892） | `conflict_sn_pair` | scientific_name 错配（原表生境/身体部位宏基因组 ↔ infer 宿主/错置生境） |

> `冲突项目数` = 各 `*_conflict_projects.csv` 的项目数；`重合项目数` = 该项目下**至少 1 条 run 同时有 infer_value 与原表字段有效值**的项目总数（country 12,652 / date 2,326 / host 17,892；三维度均于 2026-08-16 用扩展 PLACEHOLDER 统一判定 orig/infer 两端非空后重跑；host 自 2026-08-16 起以 `scientific_name` 为原表字段）。

---

## 1. Country — `tmp.country.genuine_conflict_projects.csv`

> 注：`final_country.jsonl` 中 `NotCountry:*` 值**仅按值描述本身**判定——仅「海洋/公海」与「多国/全球聚合」两类写入 `infer_value`，其余（含 `no location` / `no geographic signal` 等"无地理位置信息"类）清空；**不再使用项目 evidence note 做兜底匹配**（2026-08-16 收紧，移除 note 救回规则，仅保留 ocean/global 描述命中）。因此 `notcountry_kept` 是保留决策所致，并非推断错误。

### 1.1 按 `conflict_type`

| 冲突类型 | 项目数 | 占 1,388 | 对应了什么 |
| --- | --- | --- | --- |
| `notcountry_kept` | 646 | 46.5% | 原表 `country` 含具体国名（或海域名），infer 保留为 海洋/公海/全球聚合（`NotCountry:*`）。语义上 infer 的「无单一国家」往往是正确答案（如 PRJEB42019 orig 含 atlantic ocean / north pacific ocean），**不属 misjudge**。 |
| `fully_disjoint` | 624 | 45.0% | **强推断错误**：infer 引入的国家/大区在原表所有 run 完全不存在（如 PRJEB40383 infer=Uganda 但 orig 全为 Malawi；PRJEB6070 Kyoto→Japan 但 orig 为 France/Germany）。最应回查 `final_country.jsonl` 修正。 |
| `incomplete_subset` | 116 | 8.4% | **推断过窄（非真矛盾）**：infer 国家 ⊆ 原表国家，只抓到原表部分国家（如 PRJEB32762 infer=Argentina 但项目主体为 US）。补全仍可用。 |
| `other` | 2 | 0.1% | 原表 `country` 为 `missing: sample group`/`missing: control sample` 等带后缀占位符，躲过空值判定但被 `norm()` 归空、分布为空、无法归类（假阳性冲突，共 11 run）。 |

### 1.2 按 `misjudge_source`（infer 端误判来源）

| 误判来源 | 项目数 | 占 1,388 |
| --- | --- | --- |
| `llm` | 1,117 | 80.5% |
| `rule` | 187 | 13.5% |
| `rule_place` | 50 | 3.6% |
| `rule_demonym` | 28 | 2.0% |
| `rule_open_ocean` | 6 | 0.4% |

- 真正需修正的强错 = `fully_disjoint`（624）+ `incomplete_subset`（116）+ `other`（2）= **742** 个；`notcountry_kept`（646）为保留决策、非误判、无需排除。

### 1.3 代表性示例

- `notcountry_kept`：`PRJNA656268`（infer=NotCountry:global ocean multi-region，orig 全为 indian/atlantic/pacific/southern ocean）、`PRJEB42019`（infer=NotCountry:global，orig 含 atlantic ocean / north pacific ocean）。
- `fully_disjoint`：`PRJEB40383`（Uganda vs Malawi，rule_place）；`PRJEB6070`（Kyoto→Japan vs France/Germany，rule_place）；`PRJEB17632`（asia vs Kazakhstan/Germany，rule，continent 非国家）。
- `incomplete_subset`：`PRJEB32762`（Argentina:Buenos Aires vs orig=US 1590/Argentina 908/UK 630，rule_place 只抓到首府）；`PRJEB5224`（China vs orig=Spain 318/Denmark 244/China 17，rule_demonym，「Chinese」误归）。
- `other`：`PRJNA1135464`（orig=`missing: sample group`×10，infer=atlantic）、`PRJDB16160`（orig=`missing: control sample`，infer=United States）。

---

## 2. Date — `tmp.date.genuine_conflict_projects.csv`

> 口径：自 `NotDate` 推断值全部清空后，date 仅剩 **genuine year conflict（真年份冲突）**——原采集年集合与 infer 年份集合无交集（逐年份集合比对，非区间）。比对轴为 `collection_date` 年份集合 ↔ infer 年份集合。

### 2.1 按 `conflict_side`（年份偏早还是偏晚）

| 冲突方向 | 项目数 | 占 339 | 对应了什么 |
| --- | --- | --- |
| `orig_before_interval` | 146 | 43.1% | **infer 把年份定得偏晚（高估）**：原表采集年整体早于 infer 年份集合（infer 抽到更晚的年份，如论文发表年/项目启动年）。 |
| `orig_after_interval` | 145 | 42.8% | **infer 把年份定得偏早（低估）**：原表采集年整体晚于 infer 年份集合（infer 抽到更早的年份，如历史事件年/被引文献年）。 |
| `orig_before_interval\|orig_after_interval` | 48 | 14.2% | 同一项目内兼有偏早与偏晚（方向混杂）。 |

### 2.2 按 `misjudge_source`

| 误判来源 | 项目数 | 占 339 | 对应了什么 |
| --- | --- | --- | --- |
| `llm` | 238 | 70.2% | **LLM 直接臆测年份**（方法 `llm_agent`）：断言的年份不在 ENA 采集年集合内（最常见为偏早一年，如 2016 采的样本估成 2015）。 |
| `rule` | 101 | 29.8% | **规则/文献抽取错误**（方法 `literature\|rule_date` 或 `study_meta\|rule_date`）：从 EPMC 论文或 study 描述里抽出的"日期"与 `collection_date` 矛盾（多为论文发表年/项目年 ≠ 采样年）。 |

- 全部 339 个真年份冲突 **100% 来自 infer 端**（rule 抽错文本年 或 LLM 估错年），不存在"ENA 错、infer 对"。

### 2.3 示例

- **rule 偏早/估早**（orig_after_interval，infer 年份早于原表）：`PRJEB66439`（infer=2019 vs 原 2020，论文/项目年早一年，rule）；`PRJNA901878`（infer=2020 vs 原 2021-2022，LLM 估早）。
- **年份集合错配**（both）：`PRJEB34871`（infer 覆盖 2010-2017 但原表主体 2015-2016、infer 年集不含 2015，rule）；`PRJNA528511`（infer 2017/2019 vs 原 2018，LLM）。

---

## 3. Host — `tmp.host.realconflict_projects.csv`

> 注：2026-08-16 修正——host 维度实际对齐的是 **scientific_name**（`final_host.jsonl` 推断的即 scientific_name，并非 ENA `host` 字段）。冲突 = 原表 `scientific_name` 与 `infer_value`（亦为 scientific_name）不一致。两套均为 scientific_name，**同本体**，故本质全是**推断错误**（infer 把环境/生境宏基因组错标为特定宿主或错置生境），无"物种 vs 生境"的本体差异。

### 3.1 规模与误判来源

- 冲突项目 **346**（/ 重合 17,892，1.9%）；冲突 run **6,703**。
- `misjudge_source`：**llm 338（97.7%）** / **rule 8（2.3%）**（rule 含 PRJEB42019、PRJNA593850 等）。
- 与 country/date 一致：**100% 来自 infer 端错误**，原表（scientific_name）为权威。

### 3.2 冲突形态（scientific_name 错配）

原表 scientific_name 多为**环境/生境/身体部位宏基因组**（aquatic 158、body-site 87、marine/sediment 47、soil 19…），infer 却把它错标为**特定宿主**或**错置生境**。Top 错配（按项目数）：

| 原表 scientific_name → infer scientific_name | 项目数 | 含义 |
| --- | --- | --- |
| `freshwater sediment metagenome` → `soil metagenome` | 141 | **最典型误判**：淡水/水生沉积被 LLM 归为土壤（"soil" 成兜底标签） |
| `gut metagenome` → `primate metagenome` | 34 | 肠道宏基因组被臆测为灵长类宿主 |
| `gut metagenome` → `bird metagenome` | 17 | 同上，错标为鸟类 |
| `hypersaline lake metagenome` → `microbial mat metagenome` | 14 | 高盐湖错置为微生物席 |
| `feces metagenome` → `primate metagenome` | 8 | 粪便宏基因组错标灵长类 |
| `sediment metagenome` → `lake/marine/groundwater metagenome` | 23 | 沉积环境内部互换（错置生境） |
| `gut metagenome` → `horse/canine/bovine metagenome` | 11 | 肠道错标为马/犬/牛 |
| `salmonella …` → `phyllosphere metagenome` | 3 | 具体病原菌错标为植物叶际 |

> 类别级聚合：`Aquatic → Soil` 占 **148** 项目——**"soil metagenome" 被 LLM 当万能兜底**，是 host 维度最大单一误判簇。

### 3.3 代表性示例

- 水生错置土壤：`PRJEB34634`（sediment → wastewater;freshwater，llm）、`PRJNA593850`（salmonella → phyllosphere，llm）。
- 身体部位错标宿主：`PRJEB58441`（feces → primate）、`PRJNA259274`/`PRJNA831632`（gut → primate）、`PRJNA863598`（oral → canine）、`PRJNA788958`/`PRJNA880353`（gut/feces → horse）。
- 生境互换：`PRJEB42019`（marine sediment → Homo sapiens:human;soil，rule，混合错标）、`PRJNA217052`（soil → human gut;oral;skin，llm，多值过泛）。

### 3.4 修正建议

- **回查 `final_host.jsonl` 中 346 个冲突项目**：重点 141 个"水生沉积→土壤"与 34+17 个"肠道/粪便→灵长类/鸟类"——几乎全为 LLM 过度归并。
- 引入**生境词典白名单**（aquatic/marine/sediment/soil/plant/feces/gut…）约束 infer，禁止把已明确生境宏基因组改写为"soil"或具体宿主，可消除绝大部分 346 冲突。
