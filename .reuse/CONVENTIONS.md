# ENA_cleaning 项目约定（本窗口沉淀，跨窗口可沿用）

> 用途：把本项目在本窗口里定下的操作约定集中记录，便于在其它对话窗口沿用同一套设定。

## 1. 文件作用域（最强约束）

- **所有文件操作（read / ls / write / cp / edit / 删除）只能发生在 `ENA_MetaData_Cleaning_Skill/` 及其下属目录内。**
- 该树之外一律是禁区，**除非用户当场另行授权**。
- **markdown 是用户的指南（如 Replan.md / Replan_Short.md），我绝不可修改**；有不清楚/不一致处只能反馈，用户改完再继续。

## 2. 目录结构与职责（`.replan` 内）

| 目录 | 职责 |
|---|---|
| `.replan/`（根） | 自洽根目录，所有相对路径的基准 |
| `.tmp/` | 运行产物：步骤输出 csv / jsonl / stats / 临时清单 |
| `.script/` | 可编辑权威脚本副本（ENA 清洗脚本唯一源） |
| `.reuse/` | 复用资源，如 `taxid_type.tsv`；约定沉淀（如本文件） |
| `.manual/` | 用户 manual 判定 `manual_check_*.json` |
| `.workbuddy/memory/` | 项目日志 MEMORY.md / 每日 YYYY-MM-DD.md |
| `.log/` | 杂项日志 |

## 3. 文件名规范（全小写 m，大小写在 Linux/macOS 会断）

- 1.1 输出：`raw.metagenomic_wgs.csv`（落 `.tmp/`）
- 1.2 输出：`metagenomic_wgs.typed.csv`（落 `.tmp/`）
- 中间 jsonl：`ena_runs_<区间>.jsonl`
- 复用资源：`.reuse/taxid_type.tsv`
- manual：`.manual/manual_check_*.json`


## 4. host 推断值命名约定（§3.1 规则轮 + §3.2 LLM 轮共用）

`value` 须对齐 `.reuse/taxid_type.tsv` 中 `is_metagenome=1` 的 `scientific_name` 形式：
- 生境词 → `X metagenome`
- 人+部位 → `human X metagenome`
- 动物+肠道 → `X gut metagenome`
- 仅部位 → `gut/oral/skin/vaginal metagenome`（generic）
- **仅人/动物（无部位）→ 物种 scientific_name**（`Homo sapiens`/`Bos taurus`…），**不造 `human metagenome`**
- `confidence` 基线 `medium`；`is_high_evidence()` 仅看 evidence 单条 ±30 字片段判定 high。
