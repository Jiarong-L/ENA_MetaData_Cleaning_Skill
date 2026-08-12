# ENA METAGENOMIC 元数据清洗


文库来源（library source）为“METAGENOMIC”和文库策略（library strategy）为“WGS” 的数据集的run

## 路径设置 

先约定，本流程以 `./` 为根目录：脚本放在 `.script/` 中，用户补判资源（manual_check_*.json）放在 `.manual/`，稳定复用资源（taxid_type.tsv）放在 `.reuse/`，运行日志放在 `.log/`，其它一切中间流程产物放在 `.tmp/`。脚本通过 `ROOT = 父目录/.` 解析这些目录，不依赖 `.` 之外的文件。  

## 步骤 1 

### 1.1  raw.metagenomic_wgs.csv
从欧洲核苷酸档案库（ENA）查询某个run 我是否可以提取以下信息： run_accession,sample_accession,study_accession,country,location,collection_date,first_public,tax_id,host,host_tax_id,instrument_platform,instrument_model,library_layout,read_count

从欧洲核苷酸档案库（ENA）中选取yyyy年mm月dd日至yyyy年mm月dd日期间、且文库来源（library source）为“METAGENOMIC”和文库策略（library strategy）为“WGS” 的数据集的run，需要提取以上经测试显示可获取的字段。记录汇总保存到本地，注意不可能一次拉取、分年份拉取然后合并结果

结果存储在 raw.metagenomic_wgs.csv，这些我们从 ENA 爬取的元数据，是待清洗的对象。
注意，这一步获得的 study_accession 似乎是 project_accession，因此修改 raw.metagenomic_wgs.csv 相应的表头

### 1.2 metagenomic_wgs.typed.csv
对 raw.metagenomic_wgs.csv，在 tax_id 前按次序加上两列：type  scientific_name
它们来自 tax_id 对应的 NCBI taxonomy（注意，这些tax_id针对的是宏基因组样本），整条 lineage 大概长这样：unclassified sequences; metagenomes; [type (e.g. xx metagenomes)]; [scientific_name]

方法是：提取 tax_id set，批量查询后再映射回去


## 步骤 2  

对每个 project_accession：

### 2.1 project_study_meta.json
爬取 study_title/center_name/study_description 信息


### 2.2  project_literature.jsonl 

1. Accession 直查: 用**项目编号**查 Europe PMC，只留发表年**最早 2 篇**。逐篇判：
    - 非 Review / meta-analysis / 工具论文 → **`high`**（直接关联即强证据，不要求 metagenome 关键词、不过对题闸）
    - 是 Review / meta-analysis / 工具论文 → **`linkauthor`**

2. 当直查无结果时，Freetext 检索：用项目描述搜 EPMC（会带出很多话题相关论文）。定义**真关联（linked）**：单位对上（词边界 `_wb_contains`，排除 GEO_GENERIC 地理词 / DISCIPLINE 学科词）或 author 召回且姓氏核实过（`author_verified`）。

| 情况 | 结果 |
|---|---|
| linked + 含 metagenome 关键词 + 非 Review/meta-analysis/工具 | 进第 3 步 IDF_Check |
| linked，但无关键词 / 是 Review/meta-analysis/工具 | `linkauthor`（同 low，不进全文） |
| 不 linked，有单位但完全对不上 | `missing`（噪声，丢弃） |
| 不 linked，无任何单位 | `low`（交人工） |

3. 对 Freetext `high` 论文进行 IDF_Check（对题闸）：对比 ENA study（标题+描述）和 论文 的签名，须共享 ≥1 个稀有签名才能维持 'high' 评价，否则降为 `candidate`。一个词要算稀有签名，须同时满足：
    - 词长 ≥ 4 且不在停用词表
    - 全项目少见（**DF ≤ 10**，两轮交叉验证定）
    - 非通用英语高频词（**zipf ≤ 4.5**，用 wordfreq，缺库自动跳过）

> 另有第 4 道闸在 §3.2：LLM 判三字段前会先对每篇 high 论文做**主题甄别**，离题的由 `apply-demote` 从 high 降为 `candidate`（标 `demoted_by=llm_topic`）。


### 2.3 project_fulltext.jsonl （option）

之后应客户要求，再对某些项目进行全文爬取。注意，有些文章不是openAccess，不一定能下载


## 步骤 3  INFERENCE_METHOD

从不同来源的文本，推断想要的信息。
参考两个 INFERENCE_METHOD 里的规则和坑，生成我们自己的 INFERENCE_METHOD ，根据我的指示改

1. 用规则 + 字典从文本推出 `country` / `date` / `host` 等信息。对于每一个推断的值，
    - 记录 `confidence`（上下文含有采集关键词：high/medium）+ `source`（文本来源：study_meta/literature）。对于 `host` 额外 `tax_confidence`（taxa 关键词是否在同一条 evidence 片段 ±30 字窗口内强共现：high/medium）
    - 记录相关上下文，作为推断的evidence

2. LLM 推断：对所有有可信论文的项目，你（WorkBuddy 代理，本身就是 LLM）**一次读入该项目全部 evidence，同判 country/date/host 三字段**，并在同一次读取里**先做论文主题甄别**（不符主题的 high 论文标 `aligned=false`，后续降级 candidate）。LLM 结果写**独立文件**（不覆盖 §3.1 规则输出），两者一致性由 reconcile 核对。
    - 强调：要你直接读 evidence 推断，**不走外部 API**。脚本把 evidence 打印你、你一条条读、一条条判，再写入结果文件；**跑的时候注意上下文长度、自动清理，会话里不用报告任何结果（防止上下文过长）、只要保存结果即可 ----- 如果需要判定的量非常大，尝试开 sub agents 加速**
    - 默认只判有 high 论文的项目（`--scope high-paper`）；可选把无 high 论文的项目（`--scope no-high-paper` ，evidence 仅 study_meta）也判，结果写同一套文件。

3. 对于以上两步依旧无法判定的，用户会在对话中提供消息，由LLM阅读判定（必要时联网搜索）、规范化至资源文件‘manual_check_[country/data/host].json’）以供复用

4. 合并：先在 §3.2 内做**规则×LLM reconcile**（agree→high；仅一方→取该方；disagree 且置信相当→flag review；disagree 分高低→取高置信方），再由 §3.4 final_merge 把 manual 并入。final_merge 双轴：优先级A `confidence` high > medium > low > unknown；保证A的前提下、优先级B `source` manual > LLM > rule

### 流程示意：infer_host

```bash
infer_host(sources)
│
├─ 0. 扫描所有文本，五类词表命中
│   │   ├─ HOST_HUMAN_TRIGGER（human/homo sapiens…）   → hit_human
│   │   ├─ HOST_ANIMAL（动物俗名→物种 bos taurus/cow…）→ hit_animal
│   │   ├─ HOST_ENV（生境 soil/marine/sediment…）      → hit_env
│   │   ├─ HOST_SITE（部位 gut/oral/skin/fecal…）      → hit_site
│   │   └─ HOST_ANIMAL_SOFT（俗名 昆虫/灵长…）         → hit_soft
│   │
│   ├─ human_present = 有 hit_human？
│   ├─ animal_word   = 首个动物俗名
│   ├─ GUT_SITE      = 肠道类 site 词集合
│   └─ ctx_present   = 整段是否含 HOST_CTX 共存词（soft 门槛）
│
├─ 1. site 命中组合（每个 site 词一个候选值）
│   │   ├─ 有人源 + 该 site 有 human_name → "human X metagenome" (rule_host_human)
│   │   ├─ 否则：动物俗名 + site∈GUT_SITE + 动物∈ANIMAL_GUT_NAME
│   │   │        → "X gut metagenome" (rule_host_animal)
│   │   ├─ 否则：generic 且非 require_human → "X metagenome"
│   │   │        （有人源→rule_host_human，无→rule_host_env）
│   │   └─ require_human 但无人源 → 不妄判，跳过（留 §3.2）
│   │
├─ 2. 无 site 时，human/animal 独立成值（仅当 hit_site 为空）
│   │   ├─ 有人源 → "Homo sapiens" (rule_host_human)
│   │   └─ 每个动物 → 物种 scientific_name (rule_host_animal)
│   │
├─ 3. env 命中（每个 env 词一个值，与 site 无关）
│   │   对每个 hit_env → "X metagenome" (rule_host_env)
│   │
├─ 4. soft 命中（仅当 ctx_present）
│   │   对每个 hit_soft → 俗名值 (rule_host_soft，待 §3.2 精炼)
│   │
├─ 5. all_vals 空 → return None（交 blank_record / §3.2 补漏）
│
├─ 6. 按 value 去重 → unique_vals
│
└─ 7. 逐值组装（与 value 对齐）
    │   对每个值 v（及其 method/snippet）：
    │   ├─ confidence:     snippet 含 CTX_SAMPLE？ high : medium
    │   ├─ tax_confidence: method=rule_host_soft → 恒 medium
    │   │                  is_high_evidence(v,method,snippet)？
    │   │                    ├─ 三字名 host词+site词同窗 → high
    │   │                    ├─ 二字名 两词同窗           → high
    │   │                    └─ 拉丁二名法/不满足         → medium
    │   ├─ source:         study_meta / literature
    │   ├─ method:         rule_host_human/animal/env/soft（逐值，无 rule_multi_host）
    │   ├─ evidence:       {"value":v, …}
    │   └─ matched_tokens: [命中词]
    │
    └─ 含 rule_host_soft → needs_review=True
       返回 rec
```



### 流程示意：infer_date

```bash
infer_date(sources)
│
├─ 1. 扫描所有文本，正则找 4 位年份（限 1900<=y<=2100）
│   │   对每个 (sub_source, text)：
│   │   YEAR_RE 命中 → years.append((年份, sub, snippet±30字))
│   └─ 无命中 → return None（交 blank_record / §3.2 补漏）
│
├─ 2. 按年份去重（year_best：每年保留第一个命中片段）
│   ys = 排序后的唯一年份列表
│
└─ 3. 逐值组装（每年一个值，与 value 对齐）
    │   method 固定 "rule_date"（所有年份同，不再分单年/范围）
    │   对每个年份 y：
    │   ├─ value:          str(y)
    │   ├─ confidence:     该年片段含 CTX_SAMPLE？ high : medium
    │   │                  "samples collected in 2018" → high
    │   │                  "2074 genera constituted"   → medium
    │   ├─ source:         study_meta / literature
    │   ├─ method:         "rule_date"
    │   ├─ evidence:       {"value":y, "sub_source":…, "snippet":…}
    │   └─ matched_tokens: [str(y)]
    │
    └─ 返回 rec
```


### 流程示意：infer_country

```bash
infer_country(sources)
│
├─ 1. 扫描所有文本，四类词表分别命中
│   │   对每个 (sub_source, text)：
│   │   ├─ DEMONYM（居民/形容词 cypriot→Cyprus）→ countries[v] += rule_demonym
│   │   ├─ PLACE（国名/地名 cyprus→Cyprus）     → countries[v] += rule_place
│   │   ├─ REGION（区域词 europe/pacific）       → regions[word]
│   │   └─ OPEN_OCEAN（公海/深海）               → ocean.append(…)
│   │
├─ 2. 分支判定（优先级 countries > ocean > regions > None）
│   │
│   ├─【A】countries 非空（最常见）── 逐值组装
│   │   │   vals = 排序后的国家列表；对每个国家 c：
│   │   │   ├─ value:          c（规范国名）
│   │   │   ├─ confidence:     c 任一命中片段含 CTX_SAMPLE？ high : medium
│   │   │   │                  "collected from Cyprus"         → high
│   │   │   │                  "compared to data from Germany" → medium
│   │   │   ├─ source:         study_meta / literature
│   │   │   ├─ method:         rule_demonym / rule_place（逐值，无 rule_multi_country）
│   │   │   ├─ evidence:       {"value":c, …}
│   │   │   └─ matched_tokens: 该国命中原始词集合 [["cyprus","cypriot"]]
│   │   └─ 返回 rec
│   │
│   ├─【B】countries 空 + ocean 非空 + regions 空 → 公海
│   │   └─ value=["NotCountry"]  confidence=["NotCountry"]
│   │       method=["rule_open_ocean"]  matched_tokens=[["open_ocean"]]
│   │
│   ├─【C】countries 空 + regions 非空 → 区域词（无法定位到国）
│   │   └─ value=["europe","pacific"]  confidence=["medium","medium"]
│   │       method=["rule_region","rule_region"]
│   │
│   └─【D】全空 → return None（交 blank_record / §3.2 补漏）
```

### 整体流程

对每个 project_accession，先用规则匹配 （3.1 规则步）

1. 从 study_meta + high 论文 取文本 `build_sources()` 
2. infer_country / infer_host / infer_date
3. 生成一条 rec（如下），写入 <field>_infer.jsonl

```bash
{
    "project_accession": "PRJEB35612",
    "field": "host",
    "value":          ["aquatic metagenome", "soil metagenome"],      ← Taxa学名，可能会有一些俗名
    "confidence":     ["medium", "medium"],      ← CTX_SAMPLE：命中片段是否含采集词 ("collected from...")
    "tax_confidence": ["medium", "medium"],      ← is_high_evidence：host 专属，Taxa的推断是否合理
    "source":         ["study_meta", "study_meta"],
    "method":         ["rule_host_env", "rule_host_env"],
    "evidence": [
        {"value": "aquatic metagenome", "sub_source": "study_title", "snippet": "…irrigation water in microbiomes…"},
        {"value": "soil metagenome",    "sub_source": "study_title", "snippet": "…of soil and Lactuca Sativa…"}
    ],
    "matched_tokens": [["water"], ["soil"]]
}
```

然后，LLM 平行复核（§3.2，取代旧 is_residual 残差路由）。注意：进LLM = LLM 一次读整个项目的 evidence_text（study_meta + 全部 high 论文），同判三字段。

```bash
ena_agent_parallel.py  ── LLM 与规则平行，一次读取判 (country,date,host)
│
├─ batch     按 scope 选项目（默认 high-paper=有≥1篇high论文；
│            可选 no-high-paper=无high论文仅study_meta, 默认不开）
│            拼 evidence（study标题/描述 + 每篇high论文 [paper #n|pid=pmid] 分块）
│            不含 §3.1 规则输出（保持 LLM 独立、避免锚定） → agent_parallel.jsonl
│
├─ 代理判    逐项目读 evidence，一次完成两件事：
│            ① 论文主题甄别：每篇 high 论文判 aligned（与 study 主题是否相符）
│            ② 在「study_meta+相符论文」上判 country/date/host
│            → agent_llm_parallel.jsonl（每行一项目：papers 裁决 + 三字段子判定）
│
├─ merge     逐字段归一（_normalize：标量→列表/长度对齐/值域白名单）
│            → 分写 ena_llm_infer_{country,date,host}.jsonl（独立文件，不覆盖§3.1）
│            → papers 裁决写 agent_paper_verdicts.jsonl
│
├─ apply-demote  aligned=false 论文 high→candidate（标 demoted_by=llm_topic）
│            幂等：首次备份 _bak/，之后从备份重算。（§3.1 只读 high → 自动不消费）
│
└─ reconcile 规则 × LLM 合并（逐项目逐字段）：
            agree(取值集合相交)     → 并集 + high
            仅一方有值            → 取该方
            disagree 且置信相当    → flag review（暂定，暂取规则值）
            disagree 置信分高低    → 取高置信方
            双方 unknown          → unknown
            → reconciled_<field>.jsonl + review_<field>.jsonl
```

完成后，再由 §3.4 final_merge 把 manual 并入成三源终态：
```bash
<field> = country/date/host

 输入：rule(<field>_infer) + llm(ena_llm_infer_<field>) + manual(ena_manual_<field>)
        │
        ▼
 按 project_accession 取三源并集 ──► 逐项目收集候选
        │
        ▼
 排序键 =（轴A, 轴B）
   轴A：confidence 列表最高档   high/NotCountry > medium > low > unknown
   轴B：method 列表最高来源     manual > llm_agent > rule_*
        │
        ▼
 最优者 = winner
   ├─ winner 是 unknown 档 → value=null, confidence=["unknown"]
   └─ 否则                 → value/confidence 整条透传（host 附带 tax_confidence 透传）
        │
        ▼
 输出：final_<field>.jsonl + final_<field>_stats.json
```
