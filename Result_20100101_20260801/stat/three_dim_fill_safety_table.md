# 三维度 infer 补缺安全性对比表（全库基准）

口径（全库基准，2026-08-16 起三维度统一；本版为端到端统一重跑）：
- 所有项目数 = 28,321（全库 distinct `project_accession`，来自 1,248,145 run）
- 所有 run = 1,248,145
- **「原表为空」判定统一用扩展 PLACEHOLDER 集合**（三维度一视同仁，不再用各自 per-dimension 旧逻辑）：
  `""` / `missing` / `null` / `na` / `n/a` / `none` / `unknown` / `not available` / `not collected` / `not provided` / `not specified` / `not applicable` / `nan` / `-` / `--` / `1900-01-00` / `0000` / `0000-00-00` / `0000-00` / `00` / `not determined` / `not reported` / `nr` / `nd` / `nothost`
  - 并对 `missing*` / `nothost*` 前缀匹配（使 `NotHost:*` / `NotCountry:*` 占位符与 `not determined` 等明确无数据值均判为空，与 country 的 NotCountry 清空一致）。
- **三维度冲突分析脚本统一使用此 PLACEHOLDER 判定 orig/infer 非空**：`_build_tmp_country.py` + `_country_conflict.py`（country）、`_host_realconflict.py`（host）、`_date_genuine_proj_report.py`（date，infer 端亦门控）。
- 重合项目率 = 重合项目 / 所有项目数
- 冲突项目率 = 冲突项目 / 重合项目
- 重合 run 率 = 重合 run / 所有 run
- 冲突 run 率 = 冲突 run / 重合 run
- 可补缺(/所有) = (原表空 & infer 有) run / 所有 run
- **安全补缺规则**：仅对「可补缺 run 中落在非冲突项目」的部分填充；落在冲突项目的可补缺 run 不补（该项目 infer 已在重叠处被证伪，空处同样不可信）。
- 注：host 重合项目由旧口径 4,078 修正为 **3,983**——统一两端空值后，部分原 infer 为 `NotHost:*` 占位符的项目不再计入重叠。

| 维度 | 重合项目（/所有） | 冲突项目(/重合) | 重合run（/所有） | 冲突run(/重合) | 可补缺(/所有) | 语义一致? | 可否安全补 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Country** | 12,652（44.7%） | 1,388（11.0%） | 202,499（16.2%） | 59,984（29.6%） | 133,328（10.7%） | 是（同本体，归一化可比；但 run 级 29.6% 为真实异国冲突） | ⚠️ 条件安全：仅对 133,328 可补缺 run 中落在非冲突项目的 **121,729（91.3%，全库 9.8%）** 填充；冲突项目内的 11,599 run（8.7%）不补（infer 在该项目已被证伪）。 |
| **Host** | 17,892（63.2%） | 346（1.9%） | 625,504（50.1%） | 6,703（1.1%） | 4,903（0.4%） | 是（同本体，均为 scientific_name；但 346 项目/1.9% 仍被证伪） | ⚠️ 低覆盖+需校验：仅对 4,903 可补缺 run 中落在非冲突项目的 **4,901（99.96%，全库 0.4%）** 填充；冲突项目内 2 run 不补。scientific_name 已 93.6% 有值，infer 几无新增覆盖；346 个冲突项目须逐项目核查 `final_host.jsonl`。 |
| **Date** | 2,326（8.2%） | 339（14.6%） | 28,842（2.3%） | 10,359（35.9%） | 53,905（4.3%） | 是（同本体，但精度常仅年/XX） | ⚠️ 低价值+谨慎：仅对 53,905 可补缺 run 中落在非冲突项目的 **53,641（99.5%，全库 4.3%）** 填充；冲突项目内 264 run（0.5%）不补。覆盖仅 4.3% 且精度有限，仅应补非冲突项目空缺。 |

### infer_value 插补值的基数（单值 / 合集）

对三份 `{}`.csv 中 `selected_value_source = infer_value` 的 run，按其值代表几个实体分类。**country 用语义口径**（一个单元格若断言多国/全球则计为多值）；**host/date 用结构口径**（`;` 分隔即独立值，语义=结构）。

| 文件 | infer_value 插补总数 | 单值 | 合集/多值 |
| --- | --- | --- | --- |
| country.csv | 121,729 | 72,666 | 49,063 |
| host.csv | 4,901 | 4,536 | 365 |
| date.filtered.csv | 53,641 | 46,884 | 6,757 |

- **Country 单值 72,666** = 真实单国名 70,498 ＋ `NotCountry:` 单区域/单地点 2,168（如 `deep-sea`、`offshore cold seep`、`Station ALOHA`、`Mariana Trench`、`Eurasian Steppe`）。
- **Country 多值 49,063（占 40.3%）** = `NotCountry:` 多国/全球类（如 `global ocean`、`multi-country (US, Finland, Germany, Sweden; …)`、`worldwide`）。注意：这些在**结构口径**下因未用 `;` 分隔、被视为单单元格单值（即旧版"单值 121,729 / 合集 0"），但**语义上覆盖多个国家/全球**，故此处按语义口径计为多值。
- **Host 合集 365** = `;` 分隔的多生境（如 `human gut metagenome;human oral metagenome`）；其余 4,536 为单一生境/部位描述。注意：host 维度自 2026-08-16 改以 `scientific_name` 为原表字段，infer 补足量由旧口径 380,990 **骤降至 4,901**——因 `scientific_name` 已 93.6% 有值，infer 几无新增覆盖。
- **Date 单值 46,884** 精度拆分：仅年 `YYYY-XX-XX` 46,441、年-月 `YYYY-MM-XX` 351、完整 `YYYY-MM-DD` 92；**Date 合集 6,757** = `;` 分隔的多日期（如 `2007-XX-XX;2008-XX-XX`）。
- 三文件**区间均为 0**：country/host 无区间概念；date 磁盘上无 `YYYY-YYYY` 年距区间——冲突分析里的"年份区间"仅由脚本临时从 `infer_value` 的年份集合取 min/max 推导比对轴，并非 `infer_value` 字段的存储形态。

## 说明

- **「非冲突项目」是可信信号，不是「没值」**：一个非冲突项目指其**重叠部分**（orig↔infer 都有值且一致）推断可靠；它仍可能有 orig 为空的 run（落在「可补缺」里），那些空 run 正该用 infer 补。重叠部分（重合 run）本身已有值、**不补**。
- **安全补缺的实际 run 拆分**（由 `*_conflict_projects.csv` 项目集对可补缺 run 归类）：
  - Country：121,729 安全 / 11,599 跳过（冲突项目内）
  - Host：4,901 安全 / 2 跳过
  - Date：53,641 安全 / 264 跳过
- 结论：统一策略＝**只对非冲突项目的空 run 用 infer 补缺**，错误率近 0；优先级 **Country (9.8%) > Date (4.3%) > Host (0.4%)**。Country 覆盖尚可但需排除 742 真实误判项目（fully_disjoint 624 + incomplete_subset 116 + other 2，notcountry_kept 646 为保留决策非误判）；**Host 覆盖最低（0.4%）且 346 冲突项目（1.9%）须回查——`scientific_name` 已 93.6% 有值，infer 几乎无新增价值，仅作校验信号**；Date 覆盖 4.3%、价值有限。
- 三个 `{}`.csv（`country.csv` / `host.csv` / `date.filtered.csv`）已由 `_add_selected_value.py` 统一生成：`selected_value` 优先取原值，原值空且项目非冲突才用 `infer_value` 插补，并标注 `selected_value_source`（`ori_value` / `infer_value`）。其中 **host 维度的"原值"为 `scientific_name` 列**（因 `final_host.jsonl` 推断的即 scientific_name；ENA `host` 字段不直接参与，仅保留在输出中）。
