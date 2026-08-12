# ENA METAGENOMIC 元数据清洗（可复用模板）

> **数据范围**：`library_source=METAGENOMIC` & `library_strategy=WGS` 的 run。
> **本项目示例**：`ENA_cleaning`，区间 `yyyy-mm-dd ~ yyyy-mm-dd`。
> **适用范围**：任何从 ENA 拉取并补全样本元数据（`country` / `date` / `host`）的任务，仅改筛选/区间即可套用。
> **配套代码**：§2.1+§2.2+§2.3 通用脚本 **`.script/ena_associate_papers.py`**；§3.1 规则基线 **`.script/ena_infer_31.py`**；§3.2 LLM 平行推断 **`.script/ena_agent_parallel.py`**（取代旧 `ena_agent_residual.py` 残差设计）；§1.2 类型解析 **`.script/ena_taxid_type.py`**。

---

## 目录结构（`./` 为根）

本流程以 `./` 作为自洽根目录，所有脚本与中间产物均在其内部，不依赖 `.` 之外的其它项目文件/缓存（可直接作为可复用模板拷贝到任意项目）。布局如下：

```
./
├── Replan.md                 # 完整方法论
├── Replan_Short.md           # 精简版说明
├── .script/                  # 所有可复用脚本
│   ├── ena_fetch_runs.py     # 步骤 1：ENA 数据拉取
│   ├── ena_taxid_type.py     # 步骤 1.2：tax_id → type/scientific_name 解析
│   ├── ena_associate_papers.py  # 步骤 2：关联论文（study_meta / literature / fulltext）
│   ├── ena_infer_31.py       # 步骤 3.1：规则 + 字典基线推断
│   ├── ena_agent_parallel.py # 步骤 3.2：LLM 平行推断（与规则平行，一次读取判三字段+论文主题甄别）
│   ├── ena_agent_residual.py # （已弃用）旧 §3.2 残差裁定，保留备查
│   ├── ena_load_manual.py    # 步骤 3.3：读 .manual/ 资源落库
│   └── ena_final_merge.py    # 步骤 3.4：三源合并
├── .manual/                  # 用户补判资源（跨项目复用库）
│   └── manual_check_country.json   # manual_check_*.json（glob；仅 country 已生成 17 条）
├── .reuse/                   # 跨步骤复用、非中间产物的稳定资源
│   └── taxid_type.tsv        # tax_id → scientific_name/type（步骤 1.2 产出，稳定复用）
├── .log/                     # 运行日志
│   └── run_YYYY-MM-DD.log    # _replan_log() 统一追加；异常静默
└── .tmp/                     # 其它一切中间流程产物（断点续跑、可重建）
```

**路径约定**：脚本均位于 `.script/`，通过 `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`（即 `./`）解析其余目录；`.manual/`→`MANUAL_DIR`、`.reuse/`→`REUSE_DIR`、`.log/`→`LOG_DIR`、`.tmp/`→`TMP_DIR`。运行日志统一走 `_replan_log(msg)` 追加到 `.log/run_YYYY-MM-DD.log`。

---

## 红线 / 原则（不可违背）

- **papersource=high 的论文文本为可信源**（与 ENA 自述同等），可直接用于 high 推断；`linkauthor` 质量等同 low、不进 §2.3 全文下载、不参与自动推断；`candidate`（high 但未过对题闸 / 被 LLM 判离题）不参与自动推断；`low` 进人工队列、`missing` 丢弃，二者不参与自动推断。后续分析不再有弱源。
- `llm_infer_*` 仅由写入脚本（§3.2 `merge`）写（神圣性）；禁止任何 resolver/transform 写。
- 默认**不爬全文**（title/abstract 足够；全文实测无推断增量）。
- `location` 字段**取消**（样本级经纬度已由合并表覆盖）。
- 大查询必须**分页/分片 + 断点续跑**，绝不一次性全拉。

---

## 步骤 1 — ENA 数据拉取（目前方法合理 → 保留）

- **目标**：确认从 ENA 查询某 run 能否提取指定字段，再拉取区间 `yyyy-mm-dd ~ yyyy-mm-dd`、`METAGENOMIC`+`WGS` 的 run，汇总存本地。
- **输入**：ENA Portal `read_run`；筛选 `library_source="METAGENOMIC" AND library_strategy="WGS"`；`first_public ∈ [yyyy-mm-dd, yyyy-mm-dd]`。
- **脚本**：`.script/ena_fetch_runs.py`（多种调用模式，逗号/空格皆可）：
  - `python ena_fetch_runs.py` → **默认** 2020..2026（末段 2026 截到 2026-08-01）；
  - `python ena_fetch_runs.py 2020 [2021 …]`（或 `2020,2021`）→ 按**年份**（可多个）；
  - `python ena_fetch_runs.py 2020-01-01 2026-08-10`（或 `2020-01-01,2026-08-10`）→ **任意日期区间**（精确到日，内部 `range_to_year_chunks` 按年切片、保留逐年 .jsonl + 断点续跑）；
  - `--force` → 强制重抓已存在年份（默认：某年 `.jsonl` 已存在则跳过）。
  - 模式判定优先级：**日期区间 > 年份列表 > 默认**。
- **输出**：`raw.metagenomic_wgs.csv` —— 从 ENA 爬取的原始元数据，是**待清洗的对象**。

### 1.1 输出 schema（14 列，read_run 直接返回）

| 列 | 含义 |
|---|---|
| `run_accession` | 运行 accession（主键） |
| `sample_accession` | 样本 accession |
| `study_accession` | **实为 `project_accession`**；拉取后改表头为 `project_accession`（步骤 2 才能按项目聚合） |
| `country` | ENA 记录的国家（样本级，可能空） |
| `location` | **经纬度(latlon)**，不是地名文本，别当国别名用 |
| `collection_date` | 采样日期 |
| `first_public` | 公开发布日期（与 `collection_date` 并列保留，作时间维度） |
| `tax_id` | 分类学 id（宏基因组样本；其前方依次插入衍生列 `type`、`scientific_name`，见 §1.2） |
| `host` | 宿主（ENA 侧 = 宿主生物，非生境） |
| `host_tax_id` | 宿主分类学 id |
| `instrument_platform` | 测序平台 |
| `instrument_model` | 测序仪型号 |
| `library_layout` | 单端 / 双端 |
| `read_count` | 读段数 |

- **易错点**：不能一次拉取 → 分年份拉取再合并；`study_accession` 即 `project_accession` 须改表头；ENA search **不支持深 offset 分页**（offset≥100000 返 400）→ 须对日期区间二分切分；各年区间互不重叠，合并直接拼接、无需去重；断点续跑（某年文件存在则跳过，原子写临时文件再 rename）。

### 1.2 衍生列 `type` / `scientific_name`（NCBI taxonomy lineage 解析）

- **目标**：针对宏基因组样本的 `tax_id`，在 `tax_id` **前方依次插入两列** `type`、`scientific_name`，使列序变为 `… , type, scientific_name, tax_id, host_tax_id, …`。两列均来自该 `tax_id` 在 **NCBI taxonomy** 的完整 lineage。
- **lineage 模板**（metagenome 类型，NCBI/ENA 固定锚点 `metagenomes` = tax_id 256318）。以 ENA taxonomy API 为例，返回 `scientificName`（自身名）+ `lineage`（祖先路径，**不含自身**）+ `metagenome: true/false` 标志：
  ```
  lineage:  unclassified sequences → metagenomes → [type: xx metagenomes]
  self:     [scientific_name]   (e.g. human gut metagenome)
  ```
  - `type` = `lineage` 中位于 `metagenomes` 锚点之后、名字形如 `* metagenomes` 的层；若存在多层，取**最具体**一层（离自身最近）。
  - `scientific_name` = `tax_id` 自身的科学名（来自 `scientificName` 字段，如 `human gut metagenome`）。
  - `metagenome: false`（或 lineage 无 `metagenomes` 节点）→ `type` 留空（`NA`）；`scientific_name` 仍填自身名（多为具体菌）。
- **解析规则**：
  1. **批量**查 NCBI taxonomy Entrez `efetch`（db=taxonomy，逗号分隔多 ID，单批 ≤200）取完整有序 lineage —— **实测 ENA 的 taxonomy REST 不支持逗号批量，NCBI efetch 支持批量且沙箱内用 `verify=False` 绕过 TLS 即可**。
  2. 若 lineage 含 `metagenomes` 节点 → `type` = 其上最具体的 `* metagenomes` 子层；`scientific_name` = 该 tax_id 的科学名。
  3. 若 lineage **不含** `metagenomes`（即 `tax_id` 指向具体生物 / 宿主 / 污染，非 metagenome 本身）→ `type` 留空（`NA`）；`scientific_name` 仍填 NCBI 实际科学名（回退，多为具体菌名）。
- **实现 / 脚本**：`.script/ena_taxid_type.py`（NCBI efetch 批量 200/req，遵守 3 req/s 限速，沙箱内 `verify=False` 绕过 TLS）。输入主表 `tax_id` 列 → 输出 `.reuse/taxid_type.tsv`（`tax_id / scientific_name / type / is_metagenome`）+ 回填列。
- **回填主表（step 1 落表）**：脚本 `--backfill` 输出 **新文件** `.tmp/metagenomic_wgs.typed.csv`（原 `raw.metagenomic_wgs.csv` 不动，非破坏性）。列序 `…, type, scientific_name, tax_id, host_tax_id, …`。
- **下游衔接**：步骤 2 通用脚本 `.script/ena_associate_papers.py` 的默认 `--src` 已指向本表（`metagenomic_wgs.typed.csv`）。

---

## 步骤 2 — 逐 project_accession 收集文本证据

对每个 `project_accession`（= 步骤 1 已统一表头的 `study_accession`）：

### 2.1 爬取 ENA 自述（强源）

- **目标**：取 `study_title` / `center_name` / `study_description`。
- **输入**：ENA portal `result=study`，按 `study_accession`（即 `project_accession`）批量（每批 ≤80）。
- **输出**：`project_study_meta.json` → `{study_acc: {study_title, center_name, study_description}}`。
- **脚本**：`.script/ena_associate_papers.py --phase study`（断点续跑）。
- **易错点**：这是**强源**（ENA 自述，权威），优先于任何论文信号；`center_name` 很多项目为空，勿因空误判。


### 2.2 搜索关联论文 + 标注 PaperSource 置信 

- **目标**：为每个 project 找到**真正属于它**的发表文献，给 `PaperSource` 标置信：`high` / `linkauthor` / `low` / `missing` / **`candidate`**。
- **方法（三步，越靠前越准）**：
  1. **先用项目编号查 Europe PMC**（最准，指名道姓）：`PROJECT_ID:` / `BIOPROJECT:` / `ACCESSION_ID:` 查询，命中即真关联；**只保留按发表年（pubYear）升序最早 1–2 篇**（`ACCESSION_TOP_N=2`）。命中论文逐篇查 `is_non_primary` / `is_method_tool`：**非 Review / meta-analysis / 工具论文 → `high`**（accession 关联视为足够强，不强制 metagenome 关键词、**不过对题闸**）；**是 Review / meta-analysis / 工具论文 → `linkauthor`**。
     - 实测坑：DDBJ 来源（`PRJDB*`）在 EPMC 按上述字段**常 0 命中**，须直接走第 2 步。
  2. **查不到才用项目描述搜 Europe PMC**（free-text，四策略回退）：以 `study_title` / `description` / `center_name` 构造查询，会带出大量"话题相关"论文（不一定是本项目发的）→ 必须过**作者单位过滤 + metagenome 关键词判定 + 方法学排除**后才定型：
     - **四策略**（按序回退、`exact` 命中即短路）：`exact`（引号包完整标题短语）→ `loose`（标题实词去停用词）→ `loose_desc`（描述实词）→ `author`（`AUTHOR:"姓" 主题词`，姓取自 center 里的作者姓氏、经 `GEO_GENERIC`/`DISCIPLINE` 过滤且 `author_verified` 核实）。合并去重成候选池，记录每篇由哪个策略命中（`tag_of`）。
     - **单位匹配**：候选论文抽作者单位，与项目"强机构 token"（≥4 字母、`_wb_contains` 词边界匹配、排除 `GEO_GENERIC` 地理词与 `DISCIPLINE` 学科词如 Medicine/Anatomy/Biology）比对；命中 → 视为关联（linked）。
     - **定型（仅 free-text 分支）**：
       - 单位对上 **或** `author` 策略命中（linked）**且** 标题/摘要含 `metagenome/metagenomic/metagenomes/metagenomics/metatranscriptome/metatranscriptomic/metaproteome/metaproteomic` **且非 Review / meta-analysis / 工具论文** → 进入第 3 步**对题闸**；
       - linked 但（**无 metagenome 关键词 或 是 Review / meta-analysis / 工具论文**）→ **`linkauthor`**；
       - 有单位信息但与项目期望单位**完全无重叠** → **`missing`**（噪声，丢弃）；
       - 无单位信息 → **`low`**（进人工）。
  3. **对题闸 topic-gate（仅 free-text 的 high 候选）**：上一步定型的 `high` 论文，还须与 ENA study（标题+描述）共享 **≥1 个稀有签名 token** 才保 `high`，否则降 **`candidate`**。一个 token 算"稀有签名"须同时满足：
     - 词长 ≥ 4 且不在停用词表；
     - 全项目语料少见（IDF：**DF ≤ `TOPIC_DF_MAX`=10**，两轮交叉验证定）；
     - 非通用英语高频词（**zipf ≤ `TOPIC_ZIPF_MAX`=4.5**，用 `wordfreq`，缺库自动跳过此层）。
     - **方法学/工具论文**（`is_method_tool`：标题形如 "X: a tool/method/web server/software…"、摘要开头 "we present/develop … method/tool/pipeline"、或含 "available at|web server|github.com"）与 Review/meta-analysis 一致降 `linkauthor`，不入对题闸。
- **脚本**：`.script/ena_associate_papers.py --phase lit`（`--phase all` 一次跑完 §2.1+§2.2）。
- **输出**：`project_literature.jsonl`（每行一个项目记录，`papers[]` 含 `papersource`）。
- **运行环境**：对题闸的 zipf 层依赖 `wordfreq`，须用 venv python（`binaries/python/envs/default`）；其余阶段纯标准库。

### 2.2 输出 schema（逐字段解释）

> **产物文件 / 模式**：`project_literature.jsonl`（每项目一行；glob 匹配 `project_literature.jsonl`，唯一）。

**项目级记录（jsonl 每行）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号（= 步骤 1 的 `project_accession`） |
| `strategy` | **本次走哪条路径**：`accession`（编号直连）/ `freetext`（描述搜）/ `ERR`（异常） |
| `accession_hit` | bool；`strategy=accession` 时为 `true` |
| `query` | 实际发给 EPMC 的查询串（便于复核/复现） |
| `hitCount` | EPMC 返回命中数 |
| `papers[]` | 候选论文列表，每篇含 `papersource`（见下） |
| `error` | 仅 `strategy=ERR` 时出现 |

**`strategy` 三档**

| `strategy` | 含义 |
|---|---|
| `accession` | 编号在 EPMC 直连命中（按 pubYear 升序取最早 1–2 篇）；命中论文**非 Review / meta-analysis / 工具 → `high`**（不经单位过滤、不强制 metagenome 关键词、不过对题闸），**是 → `linkauthor`** |
| `freetext` | 编号未命中改用描述搜，返回"话题相关"候选，**须经单位过滤 + metagenome 关键词判定 + 方法学排除 + 对题闸**后才定型：`high` / `linkauthor` / `low` / `missing` / `candidate` |
| `ERR` | 处理该项目时网络/解析异常，需重跑（断点续跑自动补） |

**每篇候选论文 `papers[]` 的 `papersource` 五档**

| `papersource` | 含义 | 处置 |
|---|---|---|
| `high` | 论文**确属该项目发表**：accession 直连命中且非 Review/meta-analysis/工具；或 free-text 中"单位/作者关联"且含 metagenome 关键词、非 Review/meta-analysis/工具、且**过了对题闸** | 自动采纳为关联文献，文本可直接用于 high 推断 |
| `candidate` | free-text 单位/作者关联且非二次文献，但**未过对题闸**（与 study 无共享稀有签名），或 §3.2 被 LLM 判离题降级（`demoted_by=llm_topic`） | 疑似"同域不同研究"，不参与自动推断，待人工/复核 |
| `linkauthor` | accession 直连命中但为 Review/meta-analysis/工具；或 free-text "单位/作者关联"但**无 metagenome 关键词或是 Review/meta-analysis/工具**（同一批作者/机构对同一样本做了非宏基因组研究）；质量视作 low | 不进 §2.3 全文下载；不参与自动推断 |
| `low` | free-text 候选，论文**无作者单位信息**（无法验证是否真属本项目） | 进人工队列，不自动采纳 |
| `missing` | free-text 候选，论文**有单位但与项目期望单位完全无重叠** → 噪声 | 丢弃，不进入后续推断 |

> **关联置信即推断源强度**：仅 `papersource=high` 文本可直接用于 high 推断（与 ENA 自述同等）；`candidate`/`linkauthor`/`low`/`missing` 均不参与自动推断。

- **易错点**：accession 直连 ≠ free-text 关联（后者是关键词重叠，关联≠真相关）；单位匹配排除**学科词**与国家级地名、用词边界（`_wb_contains`），避免把同行评审/方法学论文误判 `high`；对题闸用 IDF(DF≤10)+zipf(≤4.5) 双过滤，泛词（play/located/past）不当签名；`exact` 标题短语策略命中即短路；Bing 学术不可用，free-text 只用 EPMC。


### 2.3 关联论文元数据 + 全文下载（可选，默认关）

- **目标**：取 `papersource=high` 论文作为**关联论文**，爬取其标题+摘要/全文 + 其它信息。
- **元数据（随 §2.2 一并完成）**：`--phase lit` 在 EPMC `resultType=core` 返回里**已采集**每篇论文完整字段，无需单独跑。
- **全文下载（可选，默认关）**：新增 `--phase fulltext`，从 `project_literature.jsonl` 取候选下载 EPMC free 全文到 `<out>/fulltext/`（`scope=high` 仅 high，`--fulltext-scope any` 演示用）。起初只爬标题+摘要；按需求再对部分项目做全文爬取——**注意部分文章非 openAccess，不一定能下载**。
- **EPMC 全文现状（实测 2026-08）**：EPMC **REST API 直接返回 JATS XML 全文**——`GET /rest/PMC{pmcid}/fullTextXML` 对 PMC OA 论文返回完整 `<article>`。非 PMC / 非 OA 的论文无 JATS XML（404），此时回退出版商 PDF 或仅用标题+摘要。脚本优先 XML，PDF 兜底。与红线"默认不爬全文"一致。

#### 2.3 输出 schema

**① 每篇论文记录（内嵌于 `project_literature.jsonl` 的 `papers[]`）**

| 字段 | 含义 |
|---|---|
| `pmid` / `pmcid` / `doi` | 论文标识（pmid 为 §3.2 主题甄别/降级的稳定 pid） |
| `title` / `journal` / `year` / `authors` / `abstract` / `paper_affiliations` | 论文元数据 |
| `matched_token` | 命中的项目单位 token（free-text 过滤用） |
| `papersource` | high / candidate / linkauthor / low / missing（仅 high = 可信推断源） |
| `demoted_by` | 仅被降级论文有：`llm_topic`（§3.2 LLM 判离题） |
| `full_text_urls` / `full_text_available` | EPMC 全文信息 |

**② 全文下载记录（`project_fulltext.jsonl`，仅 `--phase fulltext` 产出）**

| 字段 | 含义 |
|---|---|
| `pmid` / `pmcid` | 论文标识 |
| `file` | 下载到 `<out>/fulltext/<pmcid>.xml`（JATS，优先）或 `<pmid>.pdf`（兜底）的路径 |
| `size` / `status` / `note` | 字节数 / `ok_xml`/`ok_pdf`/`no_free`/`failed` / 失败原因 |

- **易错点**：全文优先取 JATS XML；仅非 PMC/非 OA 才回退 PDF；默认关；papersource≠high 论文不参与自动推断。


---

## 步骤 3 — INFERENCE_METHOD（从不同来源文本推断 country/date/host）

> 核心四点：**① 规则+字典基线 → ② LLM 平行推断（WorkBuddy 代理直读 evidence，不走 API） → ③ 用户消息补判 → ④ 合并**。

### 3.0 核心：每条推断逐值带质控标签 + evidence

- **逐值 `confidence`**（列表，与 `value` 对齐）：匹配片段是否处于**采集上下文**（CTX_SAMPLE：collected/sampled/recruited/enrolled/cohort/obtained/isolated/harvest/biopsy/located/origin/resident/hospital/clinic 等）。含 → `high`；不含 → `medium`。统一判据，适用于 country/date/host。
- **逐值 `tax_confidence`**（列表，**仅 host**）：由 `is_high_evidence()` 判断「分类名推断是否可靠」——单条 `evidence`（匹配词 ±30 字窗口）内 host 词与 site/env 词强共现 → `high`；否则 `medium`（soft 恒 medium）。country/date 无此栏。
- **文本来源 `source`**（列表，逐值）：`study_meta`（ENA 自述，权威）/ `literature`（仅 `papersource=high` 论文文本采用，与 ENA 自述同等可信）。`candidate`/`linkauthor`/`low`/`missing` 不参与自动推断。
- 每条推断**记录相关上下文**作为 `evidence`，供复核与 §3.2/§3.3 使用。

### 3.1 规则 + 字典基线（确定性，优先跑，high 直接采纳）

- **目标**：用规则 + 字典从文本推 `country` / `date` / `host`，产出 `high/medium/low/NotCountry/unknown`。规则判得了 high 的**直接采纳**。
- **脚本**：`.script/ena_infer_31.py`（可复用、参数化路径、自含字典 baseline、只读输入不改动任何文件）。
  - 用法：`python ena_infer_31.py`（默认读 `.tmp/` 下两输入）｜`--fields country,host`｜`--limit N`｜`--only PRJEBxxx`。
  - 输入：§2.1 `project_study_meta.json` + §2.2 `project_literature.jsonl`（仅 `papersource=high` 论文的 title/abstract）。
- **字典基线**（内建，可继续扩充）：`DEMONYM`（国籍形容词→国）/ `PLACE`（地名+国家全名+缩写→国，含 HK/TW/MO 主权归一）/ `OPEN_OCEAN`（公海/深海→`NotCountry`）/ `REGION`（洲/洋/南极/北海/地中海→medium）/ `HOST_*`（human/animal/env/soft 词表）。**注**：`HOST_*` 为手写字典，规模瓶颈在字典覆盖率；更大语料中未进字典的宿主落 `unknown`（漏检而非错判），需扩字典或换策略。
- **置信度判定标准**：
  - **country**：匹配到国名且附近有**采集上下文** → `high`；仅提及国名无上下文 → `medium`；公海/深海无主权国 → `NotCountry`（high，否定判定）；仅匹配到区域词 → `medium`；无任何匹配 → `unknown`。**不产生 `low`**。
  - **date**：提取到年份或年份合集 → `high`；无年份 → `unknown`。
  - **host**：`confidence` 判据与 country/date 一致（CTX_SAMPLE → high/medium）。此外 **`tax_confidence`**（host 专属）由证据窗口强共现判定。
  - **主权归一**：HK/TW/MO → `Hong Kong, China` / `Taiwan, China` / `Macao, China`；Korea → `Korea`；Turkey 独立真实国，勿与 Korea 混淆。
- **host 语义**：ENA 侧 = 宿主生物；描述/论文里的 soil/gut/marine 等生境词本身是合法 host 信号，勿当"无宿主"砍（脚本已对复数 lambs/ewes 等做 `s?` 容错）。
- **host High 规则（证据窗口，判定 `tax_confidence`）**：`is_high_evidence()` 只看单条 `evidence`（匹配词 ±30 字片段）：
  - **规则1（三字科学名 `<host> <site> metagenome`）**：host 指示词与中间部位词**同时**出现（部位词允许 `HOST_SITE` 同义词 gut↔feces/faeces/fecal/stool…）。
  - **规则2（仅限二字科学名 `<X> metagenome`）**：两词都出现在 evidence 中。**拉丁二名法（`Bos taurus`/`Homo sapiens` 等不以 metagenome 收尾）不适用，`tax_confidence` 恒 medium。**
  - `rule_host_soft` 的 `tax_confidence` **永不标 high**（恒 medium）。
- **输出 schema**（每字段一个 jsonl，每行一项目记录）：

> **产物文件**：`<field>_infer.jsonl`（`country_infer.jsonl`/`host_infer.jsonl`/`date_infer.jsonl`）+ `infer_stats.json`。

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `field` | `country` / `date` / `host` |
| `value` | 推断值列表（country=国名列表或 `NotCountry`；date=年列表；host=宿主列表） |
| `confidence` | **列表（逐值）**：CTX_SAMPLE → `high`/`medium`；公海 `NotCountry`；兜底 `unknown` |
| `tax_confidence` | **列表（逐值），仅 host**：证据窗口强共现 → `high`/`medium`；空记录兜底 `unknown` |
| `source` | **列表（逐值）**：`study_meta` / `literature` |
| `method` | **列表（逐值）**：`rule_demonym`/`rule_place`/`rule_open_ocean`/`rule_region`/`rule_host_*`/`rule_date`/`none` |
| `evidence` | 结构化列表 `[{"value","sub_source","snippet"}, …]` |
| `matched_tokens` | **列表的列表（逐值）** |

- **红线**：禁止确定性 resolver 直接写 `llm_infer_*`；本脚本只写 `<field>_infer.jsonl`。
- **已知规则局限（由 §3.2 LLM 平行复核兜住）**：
  - `rule_host_human` 跨宿主误判（狗/鼠/母鸡/虎粪 → `human gut metagenome`）：实测 high 层 ~29%、medium 层 ~4% 错。
  - `rule_place` 子串碰撞：`new south wales`⊃`wales`→UK、Georgia（美州名）→国家、模糊 "America"→US。
  - `rule_demonym` 聚簇错：`british columbia`→UK（同项目族 ~31 例）、German Bight 海区、German Shepherd 犬种→Germany。
  - `rule_region`/`rule_open_ocean`：global/worldwide/pacific/atlantic 等非国家值须重标 `NotCountry`。
  - 机构/试剂/署名产地（Qiagen Germany、PacBio USA）≠ 采样国；**center_name 不参与 §3.1**。
  - **date 基线不区分采集年 vs 出版/检索年**——有年份一律 `high`（已知局限）。

### 3.2 LLM 平行推断（与规则平行，WorkBuddy 代理直读 evidence，不走 API）

- **定位**：不再是「规则判不了才交 LLM」。LLM 与 §3.1 规则**平行**——对所有有可信证据的项目，代理**一次读入该项目的全部 evidence，同判 (country, date, host) 三字段**，并在同一次读取里先做**论文主题甄别**。LLM 结果写入**独立文件** `ena_llm_infer_<field>.jsonl`，**不覆盖 §3.1 输出**；规则与 LLM 的一致性在 `reconcile` 阶段核对。
- **为什么平行（而非残差路由）**：残差路由需先判「哪些单元格可信到可跳过 LLM」，而实测连白名单格也有 0.45%~3.6% 错判会被路由漏掉；平行全判则没有路由可错，且规则结果自然变成 LLM 的独立交叉验证（agree→提置信 / disagree→flag review）。同时 date 不再豁免（论文能提供规则拿不到的采集年/出版年信号）。
- **一次读取完成两件事**：
  1. **论文主题甄别**：对每篇 high 论文判「与 study 主题是否相符」。不符 → `aligned=false`，该论文由 `apply-demote` 降级 `high→candidate`，且判三字段时**不得再以它为据**（此时该项目有效证据只剩 study_meta + 相符论文）。
  2. **三字段判定**：在「study_meta + 相符论文」上判 country/date/host，逐值给 `confidence`（host 另 `tax_confidence`）。
- **scope（`--scope`，默认 `high-paper`）**：
  - `high-paper`（默认）：有 ≥1 篇 high 论文的项目（本区间 **467**）——证据最足、LLM 增益最大。
  - `no-high-paper`（**可选补充档，默认不开**）：没有 high 论文的项目（**~1539**），evidence 仅 study_meta；结果写同一套 `ena_llm_infer_<field>.jsonl`（与 high-paper 不相交、按 acc 去重）。
  - `all` / `union`：全量（2006）/ high-paper ∪ 残差 unknown。
- **流程（不走外部 API）**：`batch` 拼 evidence → **你（WorkBuddy 代理，本身就是 LLM）逐项目读、逐项目判** → 写 `agent_llm_parallel.jsonl` → `merge` 归一分写 → `apply-demote` 落降级 → `reconcile` 合并规则。工程约束：注意上下文长度、自动清理已读批次、**会话内不报告结果只落盘**；量大开 sub-agents 加速。
- **四阶段脚本 `.script/ena_agent_parallel.py`**：
  - `batch`：按 scope 拼 evidence（study 标题/描述 + 每篇 high 论文独立分块 `[paper #n | pid=pmid]`）→ `agent_parallel.jsonl`。**evidence 不含 §3.1 规则输出**（保持 LLM 独立、避免锚定）。断点续跑。
  - `merge`：读 `agent_llm_parallel.jsonl`（每行=一项目，含 `papers` 裁决 + 三字段子判定）→ 逐字段 `_normalize` 归一 → 分写 `ena_llm_infer_{country,date,host}.jsonl`；同时把 `papers` 裁决写 `agent_paper_verdicts.jsonl`。
  - `apply-demote`：把 `aligned=false` 论文在 literature 里 `high→candidate`（标 `demoted_by=llm_topic`）；**幂等**（首次备份 `_bak/project_literature.pre_demote.jsonl`，之后从备份重算）。降级后 §3.1 只读 high → 不再消费这些论文（如需 §3.1 反映需重跑 `ena_infer_31.py`）。
  - `reconcile`：规则 × LLM 合并（见下）。
- **reconcile 策略（逐项目逐字段，取代表值比较、归一小写集合）**：
  - 取值集合相交（agree）→ 并集，`confidence=high`，`method=agree`；
  - 仅一方有值 → 取该方；
  - **disagree 且置信相当 → flag review**（暂定，`needs_review=True`，暂取规则值；最终选择测试时再定）；
  - disagree 且置信分高低 → 取高置信方（`method=disagree_rule/llm`）；
  - 双方 unknown → unknown（不写 final）。
  - 产物：`reconciled_<field>.jsonl` + `review_<field>.jsonl` + `reconcile_stats.json`。
- **升级 high 的语义判据（代理直读后判定，须在 `note` 写理由）**：
  - **country → high**：明确主权国采样/采集地（单国或少数实测国），排除机构/作者贡献国、区域级、多论文混合背景国；公海/深海显式 `NotCountry`。
  - **host → high**：value 须符合 NCBI 科学名规范（对齐 `taxid_type.tsv` 中 `is_metagenome=1` 的形式：生境→`X metagenome`、人+部位→`human X metagenome`、动物+肠道→`X gut metagenome`、仅部位→`gut/oral/skin/vaginal metagenome`、human 无部位→`Homo sapiens`）。
  - **主权归一**：Hong Kong→`Hong Kong, China` / Taiwan→`Taiwan, China` / Macao→`Macao, China` / Korea→`Korea`；Turkey 勿与 Korea 混淆。
- **约束**：`llm_infer_*` 仅由 `merge` 写（神圣性）；LLM **不得凭空标 high**（无 evidence 不得编造值）。
- **与 §3.4 的关系**：`reconcile` 只做**规则 × LLM** 两源合并，输出 `reconciled_<field>.jsonl`；§3.4 `final_merge` 再把 **manual** 并入成三源终态，输出 `final_<field>.jsonl`。两者文件名已区分，无覆盖风险。

**输出 schema**

> **产物文件**：
> - `agent_parallel.jsonl`（中间：代理读，每行一项目）
> - `agent_llm_parallel.jsonl`（中间：代理写，每行一项目含三字段+papers 裁决）
> - `agent_paper_verdicts.jsonl`（中间：merge 收集的论文主题裁决）
> - `ena_llm_infer_<field>.jsonl`（最终 LLM 结果，仅 merge 写）+ `llm_infer_stats.json`
> - `reconciled_<field>.jsonl` / `review_<field>.jsonl` / `reconcile_stats.json`（reconcile 产出）

**① `agent_parallel.jsonl`（代理读）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `papers` | 该项目 high 论文映射 `[{"ref":"#1","pid":"<pmid>"}]` |
| `evidence_text` | 供直读原文（study_title + study_description + 每篇 high 论文 `[paper #n|pid=…]` 分块的 title/abstract） |

**② `agent_llm_parallel.jsonl`（代理写）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `papers` | 主题甄别 `[{"pid","aligned":true/false,"note"}]`；`aligned=false` → 降级 |
| `country` / `date` / `host` | 各为子对象 `{value[], confidence[], note}`；host 另 `tax_confidence[]`；无把握 → `value=[]` 或 `["unknown"]`；公海 → `value=["NotCountry"]` |

**③ `ena_llm_infer_<field>.jsonl`（最终，仅 merge 写）**：与 ② 子对象同口径，补 `project_accession`/`field`/`source`/`method`，经 `_normalize` 归一。

### 3.3 用户消息补判（人工高可信 `manual`）

- **目标**：§3.1（规则）与 §3.2（LLM 平行）**两步仍无法判定**的项目进入本步，由用户主动介入提供消息，LLM 阅读判定。
- **可复用资源 `manual_check_<field>.json`**（按字段各自成文件；取代原自由文本 `manual_check.txt`）：
  - **文件名**：`manual_check_country.json` / `manual_check_date.json` / `manual_check_host.json`。**目前仅 `manual_check_country.json` 已生成**（17 条，跨项目库）；`date` / `host` 待后续生成。
  - **机器从对话加载，而非人工手写**：用户在对话里贴 prose 判定，由 **LLM 抽取并规范化**为 schema 的 JSON 对象，append 进对应字段文件。人类不直接编辑；修正时对话说明、由 LLM 重写。
  - **必要时联网搜索**：LLM 主动检索项目注册库（ENA/SRA/BioProject）、机构主页、关联文献核验或补全证据。
- **输出 schema（`manual_check_<field>.json` 中每个 JSON 对象）**：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | `project_accession` | str | ✓ | ENA project accession |
  | `field` | str | ✓ | `country` / `date` / `host` |
  | `value` | list | ✓ | 国名列表 / 年列表 / host 词；多值用 list |
  | `confidence` | list | ✓ | 脚本强制 `["high"]*len(value)` |
  | `tax_confidence` | list | host | **仅 host**：强制 `["high"]*len(value)` |
  | `source` / `method` | list | 脚本补 | 强制 `["manual"]*len(value)` |
  | `evidence_basis` | str | | `direct` / `institution_inferred`（后者以提交机构国作采样国代理，证据弱） |
  | `note` | str | | **英文**证据链，可逐条追溯 |

- **国名规范**：英文 canon；`Hong Kong, China` / `Taiwan, China` / `Macao, China` 主权归一，HK/TW/MO 不可写为独立国家；Korea→`Korea`。
- **落库流程（脚本化）**：`ena_load_manual.py` 读 `.manual/manual_check_*.json` → 按 `project_accession` 去重 → 写 `ena_manual_<field>.jsonl`。**该脚本只写 `ena_manual_*.jsonl`，不碰 `ena_llm_infer_*`**。
- **定位**：`manual` 是「final 仅含规则 + LLM 文本裁定」的**唯一明确例外**——用户直接背书、等同正式裁定，在 §3.4 轴 B 中位于来源最高档。

### 3.4 合并

- **目标**：`final_merge` 按优先级合并，输出 final。
- **双轴优先级**：先保证 **轴 A（置信度）**，同级内再比 **轴 B（来源）**。
  - **轴 A（主导，由高到低）**：`high` / `NotCountry` > `medium` > `low` > `unknown`。**高置信的规则结果优先于中/低置信的 LLM 或用户结果**。
  - **轴 B（同置信度内排序）**：`manual`（用户，§3.3）> `llm_agent`（LLM，§3.2）> `rule_*`（规则，§3.1）。
- **合并步骤（逐项目·逐字段）**：
  1. 收集该项目该字段全部候选（`<field>_infer.jsonl` 的 `rule_*`；`ena_llm_infer_<field>.jsonl` 的 `llm_agent`；`ena_manual_<field>.jsonl` 的 `manual`）。
  2. 按 (轴 A tier, 轴 B rank) 升序取最小 = 胜者；候选的 `confidence`/`method` 为逐值列表，比较时各取**最高档代表值**（`_rep_conf`/`_rep_method`）。
  3. 胜者写入 final；胜者置信度为 `unknown` → `value=null` / `confidence=unknown`。
- **与 §3.2 reconcile 的关系**：§3.2 `reconcile` 已先做规则 × LLM 两源合并（输出 `reconciled_<field>.jsonl`）；本步 `final_merge` 再从三源把 manual 并入，产出最终 `final_<field>.jsonl`（两者文件名已区分）。
- **字段范围**：`country` / `date` / `host`；**`location` 字段取消**。
- **易错点**：项目级 `location` 生境 ≠ 样本级经纬度坐标，勿互填；轴 A 优先保证高置信，**勿因"用户/LLM 更权威"而用中/低置信覆盖高置信规则结果**。
- **脚本**：`ena_final_merge.py`（`--field country|date|host|all`）；只读三源、原子写、可重跑。
- **输出 schema（`final_<field>.jsonl`，每行一项目·字段最终裁定）**：

  | 字段 | 含义 |
  |---|---|
  | `project_accession` / `field` | join key / country / date / host |
  | `value` / `confidence` / `tax_confidence` / `source` / `method` | 胜者（逐值列表；host 附 tax_confidence 透传） |
  | `evidence_basis` | 仅 manual 有：`direct` / `institution_inferred` |
  | `note` | 胜者证据链 |
  | `n_candidates` / `won_by` | 候选源数量 / `sole` / `axis_A` / `axis_B` |

  配套 `final_<field>_stats.json`。

---

## 护栏清单（机器可机检）

- **G1** `llm_infer_*` 仅写入脚本（§3.2 `merge`）可写。
- **G2** 默认无全文爬取（检查是否存在 fulltext 抓取步骤）。
- **G3** `location` 字段冻结（合并表不含独立的项目级 location 推断列）。

## 反模式（一行一条）

- 确定性 resolver 写 `llm_infer_*` → 污染真裁定（3.1）
- 全文爬取 → 浪费无增量（2.3）
- `location` 重建 → 与样本坐标同名异义，已废弃（3.4）
- 一次性全拉 ENA → 超时/截断，必须分页+续跑（1）
- EPMC 关键词检索当权威绑定 → 误关联（2.2）
- 把机构/试剂/署名产地（Qiagen Germany、PacBio USA）当采样国 → 误判（3.1 坑清单）
- LLM 凭空标 high（无 evidence 编造值）→ 违反神圣性（3.2）
- 残差路由按 confidence 白名单跳过 LLM → 漏掉白名单格 0.45%~3.6% 错判（已被 §3.2 平行架构取代）
