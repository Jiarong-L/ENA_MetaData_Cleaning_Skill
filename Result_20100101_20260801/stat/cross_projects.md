# 跨维度项目清单总结（基于 selected_value 列）

口径：对 `country.csv` / `host.csv` / `date.filtered.csv`，按 `project_accession` 分组，统计每个项目内**非空 distinct `selected_value`** 个数；≥2 即记为“跨X项目”。空值不计入；不区分 `ori_value` / `infer_value` 来源（即“跨”可能来自原表本就多值，也可能来自对空 run 的 infer 插补）。

> **Host 维度说明（2026-08-16 起）**：host 回填目标为 `scientific_name` 列，故此处“跨宿主”实为**跨 scientific_name / 跨物种或生物类群**（如某项目同时含 `human gut metagenome`、`soil metagenome`、具体菌名等）。ENA 原始 `host` 字段（物种名/样本条码）不参与。

## 总体

| 维度 | 有非空 selected_value 的项目 | 跨…项目数 | 占比 |
| --- | --- | --- | --- |
| **Country（跨地域）** | 25,550 | **1,872** | 7.3% |
| **Host（跨宿主 / 跨 scientific_name）** | 27,058 | **1,551** | 5.7% |
| **Date（跨时间）** | 24,660 | **5,714** | 23.2% |

## distinct 值个数分布（按项目数，仅跨X项目，即 ≥2 个）

| distinct 值个数 | Country（跨地域） | Host（跨宿主） | Date（跨时间） |
| --- | --- | --- | --- |
| 2 | 874 | 964 | 1,454 |
| 3 | 334 | 290 | 823 |
| 4 | 150 | 69 | 526 |
| 5 | 83 | 44 | 325 |
| 6-10 | 229 | 80 | 854 |
| 11-20 | 114 | 55 | 639 |
| 21+ | 88 | 49 | 1,093 |

> 单值项目（仅 1 个 distinct 值，不计入“跨”）未列入：Country 23,678 / Host 25,507 / Date 18,946。各维度 distinct 值最多的项目分别达 412 / 6,004 / 1,045 个。

## 极端项目示例（distinct 值最多，各取前 5）

### Country（跨地域）

| project_accession | n_distinct | 部分 distinct 值（按频次降序，截断） |
| --- | --- | --- |
| PRJNA671748 | 412 | Hong Kong:residence 2 door knob day 2 day | Hong Kong:residence 3 left palm day 7 day | Hong Kong:residence 4 bed headboard day 4 night | Hong Kong:residence 4 bed headboard day 8 night …(共412个) |
| PRJNA1032917 | 384 | Spain | Netherlands | Denmark | Sweden: Norrbotten County …(共384个) |
| PRJNA722771 | 187 | Hong Kong: Peng Chau Pole-replicate3 | Hong Kong: Peng Chau Pole-replicate1 | Hong Kong: Sai Wan Ho Floor-replicate1 | Hong Kong: Tai O Handrail-replicate5 …(共187个) |
| PRJNA1245607 | 108 | China:Hainan_74 | China:Hainan_73 | China:Hainan_107 | China:Hainan_99 …(共108个) |
| PRJEB42019 | 100 | Ukraine:City of Chernobyl | Australia:Queensland:Great Barrier Reef:Davies Reef | United States of America:State of Georgia:Atlanta Zoo | United States of America:State of Alaska:City of Fairbanks …(共100个) |

### Host（跨宿主 / 跨 scientific_name）

| project_accession | n_distinct | 部分 distinct 值（按频次降序，截断） |
| --- | --- | --- |
| PRJNA348753 | 6,004 | Alteromonas australica | Lactobacillus acetotolerans | Leptospirillum ferriphilum | Methanothrix harundinacea …(共6004个) |
| PRJNA417962 | 598 | Gammaproteobacteria bacterium | Clostridiales bacterium | Lachnospiraceae bacterium | Oscillospiraceae bacterium …(共598个) |
| PRJNA480137 | 359 | Candidatus Bathyarchaeota archaeon | Chloroflexota bacterium | bacterium | Deltaproteobacteria bacterium …(共359个) |
| PRJEB38078 | 187 | Anser anser | Giraffa camelopardalis | Capra ibex | Connochaetes taurinus …(共187个) |
| PRJNA932263 | 149 | Prevotella bivia | Enterobacter hormaechei | Segatella copri CAG:164 | Phascolarctobacterium succinatutens …(共149个) |

### Date（跨时间）

| project_accession | n_distinct | 部分 distinct 值（按频次降序，截断） |
| --- | --- | --- |
| PRJEB70237 | 1,045 | 2017-08-15 | 2017-07-18 | 2017-08-23 | 2018-02-13 …(共1045个) |
| PRJNA656268 | 932 | 2011-10-05T09:32:00Z | 2014-09-23T08:47:00Z | 2011-10-11T12:18:00Z | 2013-09-01T17:47:00Z …(共932个) |
| PRJNA900041 | 830 | 2019-09-11 | 2019-09-10 | 2019-09-06 | 2018-03-03 …(共830个) |
| PRJNA900180 | 830 | 2019-12-15 | 2019-12-14 | 2019-12-13 | 2019-12-12 …(共830个) |
| PRJNA1060349 | 722 | 2011-04-09 | 2011-02-12 | 2011-12-11 | 2011-05-14 …(共722个) |

## 交付文件

- `country_cross_projects.csv` — 1,872 个跨地域项目（含 `project_accession` / `n_runs` / `n_distinct_selected_value` / `distinct_values`）
- `host_cross_projects.csv` — 1,551 个跨宿主项目（**基于 scientific_name 口径**，已重算）
- `date_cross_projects.csv` — 5,714 个跨时间项目

> 说明：country 的“跨地域”含部分为“真实国家 ↔ NotCountry 描述”混排（如某 run 为 `Norway`、另一 run 为 `global ocean`），严格说属“混合”而非“跨多国”。如需仅统计“跨真实多国”或区分原表多值 vs infer 插补造成多值，可另出过滤版。
