# ENA METAGENOMIC 元数据清洗（可复用模板）

> **数据范围**：`library_source=METAGENOMIC` & `library_strategy=WGS` 的 run。
> **本项目示例**：`ENA_cleaning`，区间 `yyyy-mm-dd ~ yyyy-mm-dd`。
> **适用范围**：任何从 ENA 拉取并补全样本元数据（`country` / `date` / `host`）的任务，仅改筛选/区间即可套用。
> **配套代码**：§2.1+§2.2+§2.3 通用脚本 **`.script/ena_associate_papers.py`**（已小批验证，断点续跑、路径参数化，只读 `--src` 不改动 `./` 外文件）；§3.1 规则基线 **`.script/ena_infer_31.py`**；§1.2 类型解析 **`.script/ena_taxid_type.py`**。

---

## 目录结构（`./` 为根）

本流程以 `./` 作为自洽根目录，所有脚本与中间产物均在其内部，不依赖 `.` 之外的其它项目文件/缓存（可直接作为可复用模板拷贝到任意项目）。布局如下：

```
./
├── Replan.md                 # 完整方法论（本文件）
├── Replan_Short.md           # 精简版说明
├── .script/                  # 所有可复用脚本（根目录 . 下的 ena_*.py / 测试脚本等）
│   ├── ena_fetch_runs.py     # 步骤 1：ENA 数据拉取
│   ├── ena_taxid_type.py     # 步骤 1.2：tax_id → type/scientific_name 解析
│   ├── ena_associate_papers.py  # 步骤 2：关联论文（study_meta / literature / fulltext）
│   ├── ena_infer_31.py       # 步骤 3.1：规则 + 字典基线推断
│   ├── ena_agent_residual.py # 步骤 3.2：LLM 残差裁定
│   ├── ena_load_manual.py    # 步骤 3.3：读 .manual/ 资源落库
│   ├── ena_final_merge.py    # 步骤 3.4：三源合并
│   ├── analyze_taxids.py     # 复用/诊断辅助
│   └── run_replan_test.py    # 端到端冒烟测试
├── .manual/                  # 用户补判资源（跨项目复用库）
│   └── manual_check_country.json   # manual_check_*.json（glob；仅 country 已生成 17 条）
├── .reuse/                   # 跨步骤复用、非中间产物的稳定资源
│   └── taxid_type.tsv        # 8,289 行 tax_id → scientific_name/type（步骤 1.2 产出，稳定复用）
├── .log/                     # 运行日志
│   └── run_YYYY-MM-DD.log    # _replan_log() 统一追加；异常静默
└── .tmp/                     # 其它一切中间流程产物（断点续跑、可重建）
```

**路径约定**：脚本均位于 `.script/`，通过 `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`（即 `./`）解析其余目录；`.manual/`→`MANUAL_DIR`、`.reuse/`→`REUSE_DIR`、`.log/`→`LOG_DIR`、`.tmp/`→`TMP_DIR`。运行日志统一走 `_replan_log(msg)` 追加到 `.log/run_YYYY-MM-DD.log`。

---

## 红线 / 原则（不可违背）

- **papersource=high 的论文文本为可信源**（与 ENA 自述同等），可直接用于 high 推断；papersource=linkauthor 质量等同 low、不进 §2.3 全文下载、不参与自动推断；papersource=low 进人工队列、missing 丢弃，二者不参与自动推断。后续分析不再有弱源。
- `llm_infer_*` 仅由 `agent_write` 写（神圣性）；禁止任何 resolver/transform 写。
- 默认**不爬全文**（title/abstract 足够；全文实测无推断增量）。
- `location` 字段**取消**（样本级经纬度已由合并表覆盖）。
- 大查询必须**分页/分片 + 断点续跑**，绝不一次性全拉。

---

## 步骤 1 — ENA 数据拉取（目前方法合理 → 保留）

- **目标**：确认从 ENA 查询某 run 能否提取指定字段，再拉取区间 `yyyy-mm-dd ~ yyyy-mm-dd`、`METAGENOMIC`+`WGS` 的 run，汇总存本地。
- **输入**：ENA Portal `read_run`；筛选 `library_source="METAGENOMIC" AND library_strategy="WGS"`；`first_public ∈ [yyyy-mm-dd, yyyy-mm-dd]`。
- **脚本**：`.script/ena_fetch_runs.py`（`python ena_fetch_runs.py` yyyy-mm-dd  yyyy-mm-dd）。
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
  - `type` = `lineage` 中位于 `metagenomes` 锚点之后、名字形如 `* metagenomes` 的层；若存在多层（如 `ecological metagenomes → environmental metagenomes`），取**最具体**一层（离自身最近）。**已验证**：`human gut metagenome`(408170) 的 lineage = `unclassified sequences; metagenomes; organismal metagenomes` → `type = organismal metagenomes`。
  - `scientific_name` = `tax_id` 自身的科学名（来自 `scientificName` 字段，如 `human gut metagenome`）。
  - `metagenome: false`（或 lineage 无 `metagenomes` 节点）→ `type` 留空（`NA`）；`scientific_name` 仍填自身名（多为具体菌）。
- **解析规则**：
  1. **批量**查 NCBI taxonomy Entrez `efetch`（db=taxonomy，逗号分隔多 ID，单批 ≤200）取完整有序 lineage —— **实测 ENA 的 taxonomy REST 不支持逗号批量（GET 404 / POST 405），NCBI efetch 支持批量且沙箱内用 `-k` 绕过 TLS 拦截即可**。8,289 个 unique `tax_id` 仅需 **~42 次请求**全部拿完（非逐条查询）。
  2. 若 lineage 含 `metagenomes` 节点 → `type` = 其上最具体的 `* metagenomes` 子层；`scientific_name` = 该 tax_id 的科学名。
  3. 若 lineage **不含** `metagenomes`（即 `tax_id` 指向具体生物 / 宿主 / 污染，非 metagenome 本身）→ `type` 留空（`NA`）；`scientific_name` 仍填 NCBI 实际科学名（回退，多为具体菌名）。
- **实现 / 脚本**：`.script/ena_taxid_type.py`（NCBI efetch 批量 200/req，遵守 3 req/s 限速，沙箱内 `verify=False` 绕过 TLS）。输入主表 `tax_id` 列 → 输出 `.reuse/taxid_type.tsv`（8,289 行：`tax_id / scientific_name / type / is_metagenome`）+ 回填列（见下）。**已实测跑通**：42 批请求覆盖全部 8,289 unique，无失败。
- **回填主表（step 1 落表）**：脚本 `--backfill` 输出 **新文件** `.tmp/metagenomic_wgs.typed.csv`（原 `raw.metagenomic_wgs.csv` 不动，非破坏性）。列序 `…, type, scientific_name, tax_id, host_tax_id, …` 符合要求；`type` 升级为 NCBI 真实子层（`organismal metagenomes` / `ecological metagenomes` / `engineered metagenomes`），`scientific_name` = NCBI 名。除下方两列外，其余列与原表完全一致（行数不变）。
  - **产物文件 / 模式**：`.tmp/metagenomic_wgs.typed.csv`（glob：`metagenomic_wgs.typed.csv`，单文件，全量落表）。
  - **下游衔接**：步骤 2 通用脚本 `.script/ena_associate_papers.py` 的默认 `--src` 已指向本表（`metagenomic_wgs.typed.csv`），与 §1.2 完全自洽；原 `raw.metagenomic_wgs.csv` 仅作为非破坏性原始存档保留。
  - **输出 schema（仅列出本步新增的两列）**：
    | 列名 | 含义 | 取值 |
    |---|---|---|
    | `type` | 宏基因组类型子层 | `* metagenomes` 最具体层（`organismal metagenomes` / `ecological metagenomes` / `engineered metagenomes`）；非 metagenome 或裸 `metagenome` 节点 → 空（`NA`） |
    | `scientific_name` | `tax_id` 在 NCBI 的科学名 | 如 `human gut metagenome`、`Homo sapiens`、`Shewanella putrefaciens` 等 |



---

## 步骤 2 — 逐 project_accession 收集文本证据

对每个 `project_accession`（= 步骤 1 已统一表头的 `study_accession`）：

### 2.1 爬取 ENA 自述（强源）

- **目标**：取 `study_title` / `center_name` / `study_description`。
- **输入**：ENA portal `result=study`，按 `study_accession`（即 `project_accession`）批量（每批 ≤80）。
- **输出**：`project_study_meta.json`（glob `project_study_meta.json`，唯一）→ `{study_acc: {study_title, center_name, study_description}}`。
- **脚本**：`.script/ena_associate_papers.py --phase study`（断点续跑）。
- **易错点**：这是**强源**（ENA 自述，权威），优先于任何论文信号；`center_name` 很多项目为空，勿因空误判。


### 2.2 搜索关联论文 + 标注 PaperSource 置信 

- **目标**：为每个 project 找到**真正属于它**的发表文献，给 `PaperSource` 标置信：`high` / `linkauthor` / `low` / `missing`。
- **方法（两步，越靠前越准）**：
1. **先用项目编号查 Europe PMC**（最准，指名道姓）：`PROJECT_ID:` / `BIOPROJECT:` / `ACCESSION_ID:` 查询，命中即真关联 → `high`；**只保留按发表年（pubYear）升序最早 1–2 篇**（后续关联可能只是引用、不详细描述本项目，且可滤掉晚于项目的疑似假阳性）。
     - 实测坑：DDBJ 来源（`PRJDB*`）在 EPMC 按上述字段**常 0 命中**（连 `ACCESSION_ID` 也多为 0），须直接走第 2 步。
  2. **查不到才用项目描述搜 Europe PMC**（free-text，四策略回退）：以 `study_title` / `description` / `center_name` 构造查询，会带出大量"话题相关"论文（不一定是本项目发的）→ 必须过**作者单位过滤 + metagenome 关键词判定**后才定型：
     - **四策略**（按序回退、`exact` 命中即短路）：`exact`（引号包完整标题短语）→ `loose`（标题实词去停用词/通用词）→ `loose_desc`（描述实词）→ `author`（`AUTHOR:"姓" 主题词`，姓取自 center 里的作者姓氏）。合并去重成候选池，并记录每篇由哪个策略命中（`tag_of`）。
     - **单位匹配**：候选论文抽作者单位，与项目"强机构 token"（≥4 字母、排除地理州名如 Japan/China 与**学科词**如 Medicine/Anatomy/Biology，避免假阳性）比对；`center_name` 提取的强机构 token 在 paper 作者单位里命中 → 视为关联(linked)。
     - **定型（仅 free-text 分支）**：
       - 单位对上 **或** `author` 策略命中（linked）**且** 标题/摘要含 `metagenome/metagenomic/metagenomes/metagenomics/metatranscriptome/metatranscriptomic/metaproteome/metaproteomic` **且非 Review**（标题含 `review` 词 / 摘要含 `in this review`）→ **`high`**（确属本项目的真·宏基因组论文，自动采纳）；
       - linked 但（**无 metagenome 关键词 或 是 Review**）→ **`linkauthor`**（低质量：同一批作者/机构对同一样本做了非宏基因组研究，或综述而非本项目具体样本研究；宏基因组论文可能尚未发布）；
       - 有单位信息但与项目期望单位**完全无重叠** → **`missing`**（噪声，丢弃）；
       - 无单位信息 → **`low`**（进人工）。
- **脚本**：`.script/ena_associate_papers.py --phase lit`（accession 优先 + free-text 四策略 + 单位过滤 + metagenome 关键词判定；`--phase all` 一次跑完 §2.1+§2.2）。
- **输出**：`project_literature.jsonl`（每行一个项目记录，`papers[]` 含 `papersource`）。

### 2.2 输出 schema（逐字段解释）

> **产物文件 / 模式**：`project_literature.jsonl`（每项目一行；glob 匹配 `project_literature.jsonl`，唯一）。

**项目级记录（jsonl 每行）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号（= 步骤 1 的 `project_accession`） |
| `strategy` | **本次走哪条路径**：`accession`（编号直连）/ `freetext`（描述搜）/ `ERR`（异常），判断结果可信度的总开关 |
| `accession_hit` | bool；`strategy=accession` 时为 `true` |
| `query` | 实际发给 EPMC 的查询串（便于复核/复现） |
| `hitCount` | EPMC 返回命中数（accession 命中=论文本数；free-text=候选池大小） |
| `papers[]` | 候选论文列表，每篇含 `papersource`（见下） |
| `error` | 仅 `strategy=ERR` 时出现 |

**`strategy` 三档**

| `strategy` | 含义 |
|---|---|
| `accession` | 编号在 EPMC 直连命中（按 pubYear 升序取最早 1–2 篇）—— "指名道姓"权威关联，`papers[]` 全 `high`，不经单位过滤、不产生 `linkauthor` |
| `freetext` | 编号未命中改用描述搜，返回"话题相关"候选，**须经单位过滤 + metagenome 关键词判定**后才定型：`high` / `linkauthor` / `low` / `missing` |
| `ERR` | 处理该项目时网络/解析异常，需重跑（断点续跑自动补） |

**每篇候选论文 `papers[]` 的 `papersource` 四档**

| `papersource` | 含义 | 处置 |
|---|---|---|
| `high` | 论文**确属该项目发表**：accession 直连命中，或 free-text 中"单位/作者关联"且标题/摘要含 metagenome 关键词（真·宏基因组论文） | 自动采纳为关联文献，文本可直接用于 high 推断 |
| `linkauthor` | free-text 中"单位/作者关联"但：它是review、或者**标题/摘要无 metagenome 关键词**（同一批作者/机构对同一样本做了非宏基因组研究，宏基因组论文可能尚未发布）；**仅 free-text 分支产生，质量视作 low** | 不进入 §2.3 全文下载；作为"关联但待确认"的弱信号，可辅助人工判断，不参与自动推断 |
| `low` | free-text 候选，论文**无作者单位信息**（无法验证是否真属本项目） | 进人工队列，不自动采纳 |
| `missing` | free-text 候选，论文**有单位但与项目期望单位完全无重叠** → 噪声 | 丢弃，不进入后续推断 |

> **关联置信即推断源强度**：`papersource=high` 表示"这篇论文确属该项目发表"，其文本**可直接用于 high 推断**（与 ENA 自述同等）；`linkauthor`/`low`/`missing` 不参与自动推断（其中 `linkauthor` 质量等同 `low`，不进入 §2.3 全文下载）。

- **易错点**：accession 直连 ≠ free-text 关联（后者是关键词重叠，关联≠真相关）；单位匹配排除**学科词**（Medicine/Anatomy/Biology 等）与国家级地名（Japan/China），只认独特机构名/城市名，避免把同行评审/方法学论文误判为 `high`；`exact` 标题短语策略命中即短路，不强求四策略都跑；Bing 学术不可用（无结构化字段），free-text 分支只用 EPMC。


### 2.3 关联论文元数据 + 全文下载（可选，默认关）

- **目标**：取 `papersource=high` 论文作为**关联论文**，爬取其标题+摘要/全文 + 其它信息。
- **元数据（随 §2.2 一并完成）**：`--phase lit` 在 EPMC `resultType=core` 返回里**已采集**每篇论文完整字段（见下方 schema），无需单独跑。
- **全文下载（可选，默认关）**：新增 `--phase fulltext`，从 `project_literature.jsonl` 取候选下载 EPMC free 全文到 `<out>/fulltext/`，写 `fulltext_stats.json`：
  - `--phase fulltext`（默认 `scope=high`：仅 `papersource=high`；`--fulltext-limit N` 默认 5）
  - `--phase fulltext --fulltext-scope any --fulltext-limit N`（测试/演示：任何有 free 全文的候选都下）
  - 起初只爬标题+摘要+其它信息（§2.2 已得）；按需求再对部分项目做全文爬取（`project_fulltext.jsonl`）——**注意部分文章非 openAccess，不一定能下载**。
- **EPMC 全文现状（实测 2026-08，重要）**：EPMC **REST API 直接返回 JATS XML 全文**——`GET /rest/PMC{pmcid}/fullTextXML` 对开放获取（PMC OA）论文返回 `application/xml` 的完整 `<article>`（含正文、方法、结果） 纯文本。非 PMC / 非 OA 的论文无 JATS XML（404），此时回退到出版商 `Open access` **PDF**（`fullTextUrlList` 里 `style=pdf`）或仅用标题+摘要。脚本优先下 XML，PDF 作兜底。与红线"默认不爬全文"一致。

#### 2.3 输出 schema

> **产物文件 / 模式**：
> - `project_literature.jsonl`（§2.2 同文件，`papers[]` 内每篇论文记录，见 ①）
> - `project_fulltext.jsonl`（仅 `--phase fulltext` 产出；glob `project_fulltext.jsonl`，唯一）
> - `<out>/fulltext/<pmcid>.xml`（优先：JATS 全文，纯文本）/ `<pmid>.pdf`（兜底：仅当无 XML 时）
> - `fulltext_stats.json`（全文下载统计；glob `fulltext_stats.json`，唯一）

**① 每篇论文记录（内嵌于 `project_literature.jsonl` 的 `papers[]`，§2.2 已落地）**

| 字段 | 含义 |
|---|---|
| `pmid` / `pmcid` / `doi` | 论文标识 |
| `title` | 标题 |
| `journal` | 期刊 |
| `year` | 发表年 |
| `authors` | 作者串 |
| `abstract` | 摘要（已去 HTML 标签） |
| `paper_affiliations` | 作者单位列表 |
| `matched_token` | 命中的项目单位 token（free-text 过滤用） |
| `papersource` | high / linkauthor / low / missing（关联置信；high = 可信推断源，linkauthor 等同 low、不进自动推断） |
| `full_text_urls` | EPMC 全文 URL 列表（含 `style`/`source`/`avail`） |
| `full_text_available` | bool |

**② 全文下载记录（`project_fulltext.jsonl`，仅 `--phase fulltext` 产出）**

| 字段 | 含义 |
|---|---|
| `pmid` / `pmcid` | 论文标识 |
| `file` | 下载到 `<out>/fulltext/<pmcid>.xml`（JATS 全文，优先）或 `<pmid>.pdf`（兜底）的路径 |
| `size` | 字节数 |
| `status` | `ok_xml`（JATS XML 全文）/ `ok_pdf`（兜底 PDF）/ `no_free`（无 OA 全文）/ `failed`（网络错） |
| `note` | 失败原因 |

- **易错点**：全文优先取 JATS XML（文本，免抽取）；仅非 PMC/非 OA 才回退 PDF；默认关；papersource=low/missing 论文不参与自动推断。


---

## 步骤 3 — INFERENCE_METHOD（从不同来源文本推断 country/date/host）

> 核心四点：**① 规则+字典基线 → ② LLM 残差（WorkBuddy 代理直读 evidence，不走 API） → ③ 用户消息补判 → ④ 合并**。

### 3.0 核心：每条推断带两个互相独立的质控标签 + evidence

- **标签 A — 匹配内容本身的可信度**（`content_reliability`）：被匹配到的文本片段本身可不可信（明确采样声明 vs 模糊提及）。
- **标签 B — 文本来源**（`source`）：`study_meta`（ENA 自述，权威可信）/ `literature`（关联论文文本，仅 `papersource=high` 才采用，与 ENA 自述**同等可信**）。`papersource=linkauthor`（质量等同 low）、`low` 进人工、`missing` 丢弃，不参与自动推断（沿用 §2.2 关联置信分档）。
- 两轴**互不影响**：来源强不代表内容模糊就升可信。本项目已无弱源，故实务上两轴在来源侧一致，但 `content_reliability` 仍独立刻画"片段本身的明确度"。
- 每条推断**记录相关上下文**作为 `evidence`（谁、哪段原文、怎么匹配），供复核与 §3.2/§3.3 使用。

### 3.1 规则 + 字典基线（确定性，优先跑，high 直接采纳）

- **目标**：用规则 + 字典从文本推 `country` / `date` / `host`，产出 `high/medium/low/NotCountry/unknown`。规则判得了 high 的**直接采纳**，不必进 §3.2（host 亦可由 §3.1 证据窗口 high 直接产出，见「host High 规则」）。
- **脚本**：`.script/ena_infer_31.py`（可复用、参数化路径、自含字典 baseline、只读输入不改动任何文件）。
  - 用法：`python ena_infer_31.py`（默认读 `.tmp/` 下两输入）｜`--fields country,host`｜`--limit N`｜`--only PRJEBxxx`。
  - 输入：§2.1 `project_study_meta.json`（study_title/description）+ §2.2 `project_literature.jsonl`（仅 `papersource=high` 论文的 title/abstract）。
- **字典基线**（内建，可继续扩充）：`DEMONYM`（国籍形容词→国）/ `PLACE`（地名+国家全名+缩写→国，含 USA/UK/China 等直写国名，含 HK/TW/MO 主权归一）/ `OPEN_OCEAN`（公海/深海→`NotCountry`）/ `REGION`（洲/洋/南极/北海/地中海→medium）/ `HOST_*`（human/animal/env/soft 词表，生境词即合法 host 信号；`HOST_SITE` 含 feces/faecal/stool 等同义词用于部位回退）。**注**：`HOST_*` 为手写字典，规模瓶颈在字典覆盖率；早期试过的「双名法学名 catch-all 正则兜底」已移除（其 `BINOMIAL_RE`/`ENGLISH_STOP` 等不可复用给其他项目），现 host 纯靠字典 + soft 词表 + 证据窗口 High 规则。更大/更多样语料中未进字典的宿主会落 `unknown`（漏检而非错判），需靠扩字典或换策略解决。
- **置信度判定标准（对齐 mARG/ENA）**：
  - **country**：匹配到国名且附近有**采集上下文**（collect/sample/isolat/obtain/recruit/enroll/harvest/… 或 `from the`/`across`/`throughout`）→ `high`；仅提及国名无上下文 → `medium`；公海/深海无主权国 → `NotCountry`（high，否定判定）；仅匹配到区域词（洲/洋/global）→ `medium`；无任何匹配 → `unknown`。**不产生 `low`**。
  - **date**：提取到年份或年份区间  → `high`；无年份 → `unknown`。
  - **host**：默认 `medium`（仅关键字命中，无上下文精判）；但 §3.1 现已支持**证据窗口 high** —— 当 `evidence`（匹配词 ±30 字）内能直接证明 host 值时即标 `high` 并跳过 §3.2（见下方「host High 规则」）。环境型（soil/plant/sediment）命中生境字典即 value，多为 medium；当 `soil/marine/...` 与 `metagenome` 在  evidence 时走高窗口 high。其余由 §3.2 判定后决定是否升 high。
  - **主权归一**：HK/TW/MO → `Hong Kong, China` / `Taiwan, China` / `Macao, China`（英文 canon，主权归一不可省，HK/TW/MO 不得写为独立国家）；Korea → `Korea`；Turkey 独立真实国，仅当研究确在土耳其才写 `Turkey`，**勿与 Korea 混淆**。
- **host 语义**：ENA 侧 = 宿主生物；描述/论文里的 soil/gut/marine 等生境词本身是合法 host 信号，勿当"无宿主"砍（脚本已对复数 lambs/ewes 等做 `s?` 容错）；正则把研究微生物当"物种"混入时，需下游净化。
- **host High 规则（证据窗口，§3.1 直接产出 high 不进 §3.2）**：`is_high_evidence()` 只看单条 `evidence`（匹配词 ±30 字片段），满足以下之一即标 `confidence=high`、置 `needs_review=False` 跳过 §3.2：
  - **规则1（三字科学名 `<host> <site> metagenome` 或 `<A> <B> metagenome`）**：host 指示词（human / homo sapiens，或 HOST_ANIMAL 对应俗名）**与** 中间部位词**同时**出现 —— 部位词允许 `HOST_SITE` 同义词（gut ↔ feces/faeces/fecal/faecal/stool/intestinal/intestine/colorectal/colon…）。例：`human gut metagenome` 可由 "human" + "feces" 同在 evidence 命中。
  - **规则2（仅限二字科学名 `<X> metagenome`）**：如 `soil metagenome` / `gut metagenome` / `skin metagenome` —— 两词都出现在 evidence 中。**拉丁二名法（`Bos taurus` / `Homo sapiens` / `Mus musculus` 等，不以 metagenome 收尾）不适用规则2，也不适用规则1（无 site 中间词），故永不经证据窗口标 high，保持 medium 交 §3.2。**
  - `rule_host_soft`（昆虫/灵长/爬行/植物等轻量俗名）**永不标 high**，恒交 §3.2。
- **输出 schema**（每字段一个 jsonl，每行一项目记录）：

> **产物文件 / 模式**：`<field>_infer.jsonl`（globs 到 `country_infer.jsonl` / `host_infer.jsonl` / `date_infer.jsonl`，每行一项目记录）+ `infer_stats.json`（计数汇总；glob `infer_stats.json`，唯一）。

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `field` | `country` / `date` / `host` |
| `value` | 推断值（country=国名列表或 `NotCountry`；date=年或年区间；host=生物/生境） |
| `confidence` | `high` / `medium` / `low` / `NotCountry` / `unknown` |
| `content_reliability` | **标签 A**：匹配内容本身可信度 high/medium/low |
| `source` | **标签 B**：`study_meta` / `literature` |
| `method` | 命中规则（rule_demonym/place/open_ocean/region/multi_country/host_*/date_* / none） |
| `evidence` | 命中片段 + 上下文（含 sub_source 标注） |
| `matched_tokens` | 命中的国名/年/宿主词 |

  另写 `infer_stats.json`（各字段各 confidence 计数）。
- **红线**：禁止确定性 resolver 直接写 `llm_infer_*`（污染真裁定）；本脚本只写 `<field>_infer.jsonl`，不写 `llm_infer_*`。
- **常见坑（来自 mARG/ENA 实战，务必规避）**：
  - 机构/作者**贡献国 ≠ 采样国**；试剂/设备/耗材产地（Qiagen Germany、PacBio USA）、基金机构、署名/实验室所在地，一律不计采样国。
  - **center_name 不参与 §3.1 推断**（测序中心所在国 ≠ 采样国，已从 sources 中移除）。
  - **date 基线不区分采集年 vs 出版/检索年**——有年份一律 `high`（已知局限：未来年/出版年噪声未过滤，靠 ENA 原始 date 字段质量兜底）。
  - **区域（洲/洋）≠ 国** → medium，不升 high；含大区词（Indo-Pacific）的多国 → medium 多值。
  - **国形容词盲点**（Japanese/Korean…）：国名词正则抓不到，须靠 DEMONYM 字典；但 demonym 修饰海域（Norwegian Sea→非国，走 NotCountry）、修饰工艺（Swiss-type cheese→指工艺非产地）、或地名/河名/物种名嵌国形容词（British Columbia→加拿大省、Russian River→加州河、Mexican *Gopherus berlandieri*→德州龟）极易误判，**必须 LLM 复核**（见 §3.2）。
  - **多论文混合项目**：只取本项目真正实测国，剔除其它论文背景国（如 PRJEB26069 实测 Indonesia+Fiji，剔除其它背景国）。
  - **geonoun 正则（river/lake/sea…）仅作发现器**，不直接定国（70% 噪声，ASCII 语料下"非英语"信号失效）；陌生专名捞成候选交 LLM/人工补字典。
  - **NotCountry**：公海/深海/远海/abyssal/hadal/hydrothermal vent/gyre 等无主权国样本显式标 `NotCountry`（high，否定判定），**勿当 unknown**；但 `pelagic`（开放水层）可指半封闭海（北海/Helgoland 有德国/荷兰 EEZ）或淡水，不属"明确无主权国"，已从信号词剔除，勿误判。

### 3.2 LLM 残差（规则判不了的，由 WorkBuddy 代理直读 evidence 逐条判，不走 API）

- **路由判据**：规则+字典判不了的残差——即 **`content_reliability` 不足**（medium/low/unknown）的子集（**先不管来源**，两轴独立；来源在本项目已无弱源区分）。**仅 `country` / `host` 进 §3.2 交由 LLM 做语义精判；`date` 整字段豁免**（§3.1 有年份一律 high、无年份 unknown，LLM 无必要介入）。
- **目标**：LLM 阅读 evidence，回答该字段的值（或"无法判断"）；可把规则基线 medium/low 升为 high，或把 unknown 解出值。
- **流程（强调不走外部 API）**：脚本把待判 `evidence` 打印出来 → **你（WorkBuddy 代理，本身就是 LLM）直接读**，**一条条读、一条条判**，回答字段值 → 经写入脚本追加到 `ena_llm_infer_<field>.jsonl`。
  - 用脚本分批拉待判项目（断点续跑，已完成集合自动跳过），避免一次性涌入。
- **工程约束（防上下文爆炸）**：跑时**注意上下文长度、自动清理**已读批次；**会话内不报告任何结果**（防上下文膨胀），只保存结果文件（结果由写入脚本落盘，不在对话里复述）。
- **升级 high 的语义判据（代理直读后判定，须在 `note` 写理由）**：
  - **country → high**：明确是主权国采样/采集地（单国或少数实测国），排除①机构/作者贡献国②区域级（留 medium）③多论文混合只取真正实测国；公海/深海显式 `NotCountry`（high 否定判定）。
  - **host → high**：§3.1 可能已直接产 host high（证据窗口强共现，value 形如 `human gut metagenome` / `soil metagenome`），§3.2 仅处理其残差（medium / unknown / soft 俗名）；残差中成功推断的部分可升 high（注意，两步的输出都要符合NCBI科学名的规范、流程之前已经从taxid_type.tsv中了解过）。
  - **date**：不进 §3.2（§3.1 有年份一律 high、无年份 unknown）。
  - **主权归一**：Hong Kong→`Hong Kong, China` / Taiwan→`Taiwan, China` / Macao→`Macao, China` / Korea→`Korea`；Turkey 勿与 Korea 混淆。
- **不判 high 的情况**（→ medium / low / unknown）：区域级、环境型宿主、多国未定位单一采样国、host 基线默认、证据矛盾/不足。
- **约束**：`llm_infer_*` 仅由写入脚本写（神圣性）；LLM 仅补规则判不了的残差，**不得凭空标 high**（无 evidence 不得编造值）。
- **脚本**：`.script/ena_agent_residual.py`（可复用，`batch` 抽残差+落 evidence / `merge` 校验并入；只读输入、不改源文件、对话内只打印摘要不打印 evidence）。
  - `batch`：`--field country|host` → 抽取残差写入 `agent_residual_<field>.jsonl`（含 `evidence_text` + `rule_partial`），并**自动跳过已完成集合**（断点续跑）。
  - 代理读 `agent_residual_<field>.jsonl` 逐条判，写 `agent_llm_<field>.jsonl`（判定记录，见下）。
  - `merge`：把 `agent_llm_<field>.jsonl` 并入 `ena_llm_infer_<field>.jsonl`（按 `project_accession` 去重、代理判定覆盖旧值），写 `llm_infer_stats.json`。
- **输出 schema**：

> **产物文件 / 模式**：
> - `agent_residual_<field>.jsonl`（glob `agent_residual_*.jsonl`，中间：代理读）— ①
> - `agent_llm_<field>.jsonl`（glob `agent_llm_*.jsonl`，中间：代理写）— ②
> - `ena_llm_infer_<field>.jsonl`（globs 到 `ena_llm_infer_country.jsonl` / `ena_llm_infer_date.jsonl` / `ena_llm_infer_host.jsonl`，最终：仅由 `merge` 写）+ `llm_infer_stats.json`（glob，计数汇总）— ③

**① 中间（代理读）`agent_residual_<field>.jsonl`（每行一残差项目）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `field` | `country` / `date` / `host` |
| `rule_partial` | 规则基线残留（对象）：`value` / `confidence` / `content_reliability` / `source` / `method` / `matched_tokens` |
| `evidence_text` | 已组装供直读的原文（study_title + study_description + high 论文 title/abstract） |

**② 中间（代理写）`agent_llm_<field>.jsonl`（每行一判定）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `field` | `country` / `date` / `host` |
| `value` | 国名 \| 国名列表 \| `NotCountry` \| 年 \| 宿主 \| `null`（无法判断） |
| `confidence` | `high` / `medium` / `low` / `unknown` / `NotCountry` |
| `content_reliability` | **标签 A**：匹配内容本身可信度 high/medium/low |
| `source` | **标签 B**：`study_meta` / `literature` |
| `method` | 固定 `llm_agent` |
| `note` | 英文证据链（升级 high 须在 `note` 写理由） |

**③ 最终 `ena_llm_infer_<field>.jsonl`（每行一项目记录，仅由 `merge` 写）+ `llm_infer_stats.json`（计数汇总）**

| 字段 | 含义 |
|---|---|
| `project_accession` | 项目编号 |
| `field` | `country` / `date` / `host` |
| `value` | 同 ②（合并后同口径） |
| `confidence` | 同 ② |
| `content_reliability` | 同 ② |
| `source` | 同 ② |
| `method` | `llm_agent`（若经 §3.3 并入则 `manual`） |
| `note` | 英文证据链 |
| `llm_infer_stats.json` | 各字段各 confidence 计数汇总（glob，唯一） |


### 3.3 用户消息补判（人工高可信 `manual`）

- **目标**：§3.1（规则+字典）与 §3.2（LLM 残差直读 evidence）**两步仍无法判定**的项目进入本步，由用户主动介入提供消息，LLM 阅读判定。
- **可复用资源 `manual_check_<field>.json`**（按字段各自成文件；核心变更，取代原自由文本 `manual_check.txt`）：
  - **文件名**：`manual_check_country.json` / `manual_check_date.json` / `manual_check_host.json`，对应字段 `country` / `date` / `host`。**目前仅 `manual_check_country.json` 已生成**（17 条 country 实例，跨项目库）；`date` / `host` 待各自后续生成同类文件。
  - 这是**跨项目、机器可加载**的 manual 裁定库，**不局限于测试批**。每条记录是一个项目的「用户背书高可信裁定」，全量 `final_merge` 可按 `project_accession` 直接采用。
  - **机器从对话加载，而非人工手写/编辑**：用户在对话里贴 prose 形式的判定（如"PRJXXX 采样于法国里昂临床样本，证据是…"），由 **LLM 抽取并规范化**为下方 schema 的 JSON 对象，append 进对应字段的 `manual_check_<field>.json` 数组（如 country 实例进 `manual_check_country.json`）。人类不直接编辑该文件内容；若需修正，在对话里说明、由 LLM 重写对应对象。
  - 亦支持用户随对话附其它文件（文献 PDF / 注册库导出 / 截图 / 网页），LLM 阅读后同样规范化写入。
  - **必要时联网搜索**：LLM 主动检索项目注册库（ENA / SRA / BioProject）、机构主页、关联文献（ClinicalTrials.gov / Nature 文章 / GOLD / RISE 项目站等）核验或补全证据。
- **输出 schema（`manual_check_<field>.json` 中每个 JSON 对象）**：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | `project_accession` | str | ✓ | ENA project accession |
  | `field` | str | ✓ | `country` / `date` / `host` |
  | `value` | list | ✓ | 国名列表 / 年列表 / host 词；多值用 list（如 `["Indonesia","Fiji"]`），单值也用 list（`["Gambia"]`） |
  | `confidence` | str | ✓ | manual 强制 `high` |
  | `source` | str | ✓ | `manual` |
  | `method` | str | ✓ | `manual` |
  | `content_reliability` | str | | `high`（直接证据）/ `medium`（机构归属推断，较弱）；沿用轴 A 标签，便于下游审计 |
  | `evidence_basis` | str | | `direct`（采样地/文献/注册库直接陈述）/ `institution_inferred`（以提交机构所在国作采样国代理，证据链弱于 direct） |
  | `note` | str | | **英文**证据链（来源字段 / 注册号 / 关联依据 / 检索 URL），可逐条追溯 |

- **国名规范**：采用**英文 canon**（如 `Korea` 非中文"韩国"；`Hong Kong, China` / `Taiwan, China` 按主权归一，HK/TW/MO 不可写为独立国家）；多国为 list。非 country 字段（date→年、host→生境词）同理按需规范化。
- **`evidence_basis` 语义**：`direct` 为采样地/文献/注册库直接陈述，证据强；`institution_inferred` 仅以提交机构所在国推采样国（如 PRJEB22007→`Korea`、PRJNA256007→`New Zealand`），证据链弱——仍标 `confidence=high`（用户背书），但 `content_reliability=medium` + `evidence_basis=institution_inferred` 显式标记，下游可单独审计/降权。
- **落库流程（脚本化）**：`ena_load_manual.py` 读 `.manual/manual_check_*.json`（glob，按文件名 `manual_check_<field>` 取字段）→ 按 `project_accession` 去重 → 写 `ena_manual_<field>.jsonl`（机器消费的实际 manual store）。`final_merge`（§3.4）读取 `ena_manual_*` 并按双轴优先级合并。**该脚本只写 `ena_manual_*.jsonl`，不碰 `ena_llm_infer_*.jsonl`**（后者由 final_merge 统一收口，天然避免 §3.2 merge 乱序覆盖 manual）。
- **定位**：`manual` 是「final 仅含规则 + LLM 文本裁定」的**唯一明确例外**——由用户直接背书、等同正式裁定（对齐 ENA / mARG 的 `manual` 机制），在 §3.4 轴 B 中位于来源最高档。

### 3.4 合并

- **目标**：`final_merge` 按优先级合并，输出 final。
- **双轴优先级**：先保证 **轴 A（置信度）**，同级内再比 **轴 B（来源）**——置信度是合并第一判据，来源仅作同置信度内的决胜。
  - **轴 A（主导，由高到低）**：`high` / `NotCountry`（高置信否定，等同 high 层级）> `medium` > `low` > `unknown`（无信号）。**高置信的规则结果优先于中/低置信的 LLM 或用户结果**。
  - **轴 B（同置信度内排序）**：`manual`（用户，§3.3）> `llm_agent`（LLM，§3.2）> `rule_*`（规则，§3.1）。仅当两条候选**置信度相同**时才用轴 B 决出胜者。
- **合并步骤（逐项目·逐字段）**：
  1. 收集该项目该字段全部候选（来自三源：`<field>_infer.jsonl` 的 `rule_*`；`agent_llm_<field>.jsonl` 的 `llm_agent`；`ena_manual_<field>.jsonl` 的 `manual`）。
  2. 按 (轴 A tier, 轴 B rank) 升序取最小 = 胜者；轴 A tier 相同（≥2 条）才进轴 B 决胜。
  3. 胜者写入 final；若胜者置信度为 `unknown`（无任何信号）→ `value` 置 `null` / `confidence=unknown`。
- **示例**：
  - 规则 `high`（法国）vs LLM `medium`（法国）→ **轴 A 胜**：规则 `high`（置信度压倒来源）。
  - 规则 `high`（法国）vs 用户 `manual` `high`（德国）→ 轴 A 平手（皆 high）→ **轴 B 胜**：`manual` 德国。
  - LLM `medium`（同值）vs 规则 `medium` → 轴 A 平手 → **轴 B 胜**：`llm_agent`（LLM ≥ 规则，对齐用户原话「用户 > LLM > 规则」；旧版示例误写"规则胜"，已更正）。
- **字段范围**：`country` / `date` / `host`；**`location` 字段取消**（样本级经纬度已由合并表覆盖）。
- **易错点**：项目级 `location` 生境（gut/soil…）**≠** 样本级经纬度坐标，同名异义，勿互填；轴 A 优先保证高置信，**勿因"用户/LLM 更权威"而用中/低置信覆盖高置信规则结果**（旧版"规则>LLM>用户"已废弃，改为置信度优先）。
- **脚本**：`ena_final_merge.py`（`--field country|date|host|all`）；只读三源、原子写、可重跑；**不读** `ena_llm_infer_<field>.jsonl`（那是 §3.2 内部 merge 视图，与 rule+llm 源重复，避免双计）。
- **输出 schema（`final_<field>.jsonl`，glob 到 `final_country.jsonl` / `final_date.jsonl` / `final_host.jsonl`；每行一项目·字段最终裁定）**：

  | 字段 | 含义 |
  |---|---|
  | `project_accession` | ENA 项目编号（join key） |
  | `field` | country / date / host |
  | `value` | 胜者值：国名 / 国名列表 / 年 / 宿主 / `null`（unknown 时） |
  | `confidence` | 胜者置信度：high / NotCountry / medium / low / unknown |
  | `content_reliability` | 轴 A 标签：high / medium / `null`（unknown 时） |
  | `source` | 胜者来源：study_meta / literature / manual |
  | `method` | 胜者方法：`rule_*` / `llm_agent` / `manual` |
  | `evidence_basis` | 仅 manual 有：`direct` / `institution_inferred`；其余 `null` |
  | `note` | 胜者证据链（rule 取 `evidence`，llm/manual 取 `note`） |
  | `n_candidates` | 该项目的候选源数量（审计：1=sole，>1=有竞争） |
  | `won_by` | 裁决方式：`sole` / `axis_A` / `axis_B`（轴 A 唯一 / 轴 A 平手靠轴 B） |

  配套 `final_<field>_stats.json`（glob）：`total_projects` / `by_confidence` / `by_method` / `resolved_by{sole,axis_A,axis_B}` / `truly_unknown`。

---

## 护栏清单（机器可机检）

- **G1** `llm_infer_*` 仅 `agent_write` 可写。
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

## 开放问题

- 小批验证正例偏少（仅 PRJEB11419 触发单位过滤）。建议换大批次再跑一轮，更全面地检验 accession 命中 + 单位匹配。
- 全文经 EPMC REST `/fullTextXML` 已可得 **JATS XML 纯文本**（无需 PDF 抽取）；脚本 `--phase fulltext` 优先下 XML、PDF 兜底。如后续确需更强解析，可在 XML 上做 xpath/正文抽取。

---

## 复现脚本总表（输入 / 输出 / 状态）

> 按步骤列出「复现本流程所需的脚本」。`.script/` 内脚本均只读输入、不改动 `./` 外文件、支持断点续跑；`first_public` 批次等测试产物落 `.tmp/`（仅本项目内部，不依赖其它项目文件/缓存）。

| 步骤 | 脚本 | 位置 | 输入 | 输出（文件名 / glob） | 状态 |
|---|---|---|---|---|---|
| 1 拉取 | `ena_fetch_runs.py` | `.script/` | ENA Portal `read_run`（METAGENOMIC+WGS，按年分页） | `.tmp/raw.metagenomic_wgs.csv`（14 列，待清洗） | [x] |
| 1.2 类型 | `ena_taxid_type.py` | `.script/` | 主表 `tax_id` 列（读 unique） | `.reuse/taxid_type.tsv`（8,289 行）＋ `--backfill` → `metagenomic_wgs.typed.csv`（16 列） | [x] |
| 2.1+2.2+2.3 | `ena_associate_papers.py` | `.script/` | typed.csv（`--src`，默认） | `project_study_meta.json` / `project_literature.jsonl` / `project_fulltext.jsonl` + `fulltext/*.pdf` + `fulltext_stats.json` + `associate_stats.json` | [x] |
| 3.1 规则 | `ena_infer_31.py` | `.script/` | `project_study_meta.json` + `project_literature.jsonl`（仅 high） | `country_infer.jsonl` / `host_infer.jsonl` / `date_infer.jsonl` + `infer_stats.json` | [x] |
| 3.2 LLM 残差 | `ena_agent_residual.py` | `.script/` | `<field>_infer.jsonl` | `agent_residual_<field>.jsonl` / `agent_llm_<field>.jsonl` / `ena_llm_infer_<field>.jsonl` + `llm_infer_stats.json` | [x] |
| 3.3 用户补判 | `ena_load_manual.py`（资源 `manual_check_<field>.json`） | `.script/` | 对话抽取 / `.manual/manual_check_*.json`（glob；仅 `manual_check_country.json` 已生成） | `ena_manual_<field>.jsonl`（按 field 拆分；跨项目复用库，country 已含 17 条实例） | [x] |
| 3.4 合并 | `ena_final_merge.py` | `.script/` | `<field>_infer.jsonl` + `agent_llm_<field>.jsonl` + `ena_manual_<field>.jsonl`（三源） | `final_<field>.jsonl`（glob `final_{country,date,host}.jsonl`）+ `final_<field>_stats.json` | [x] |
