# ENA_cleaning 项目约定（本窗口沉淀，跨窗口可沿用）

> 用途：把本项目在本窗口里定下的操作约定集中记录，便于在其它对话窗口沿用同一套设定。

## 1. 文件作用域（最强约束）

- **所有文件操作（read / ls / write / cp / edit / 删除）只能发生在 `ENA_MetaData_Cleaning_Skill/` 及其下属目录内。**
- 该树之外一律是禁区，**除非用户当场另行授权**。
- **markdown 是用户的指南（如 Replan.md / Replan_Short.md），我绝不可修改**；有不清楚/不一致处只能反馈，用户改完再继续。

## 2. 目录结构与职责（`.` 内）

| 目录 | 职责 |
|---|---|
| `./`（根） | 自洽根目录，所有相对路径的基准 |
| `.tmp/` | 运行产物：步骤输出 csv / jsonl / stats / 临时清单 |
| `.script/` | 可编辑权威脚本副本（ENA 清洗脚本唯一源） |
| `.reuse/` | 复用资源，如 `taxid_type.tsv`；约定沉淀（如本文件） |
| `.manual/` | 用户 manual 判定 `manual_check_*.json` |
| `.workbuddy/memory/` | 项目日志 MEMORY.md / 每日 YYYY-MM-DD.md |
| `.log/` | 杂项日志 |

