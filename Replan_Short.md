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
搜索关联论文，为 PaperSource 标注置信来源（`papersource`：high / linkauthor / low / missing）

1. 先用项目编号查 Europe PMC（最准，指名道姓；只留发表年最早 1–2 篇）。命中论文逐篇查：非 Review / meta-analysis → `high`；是 Review / meta-analysis → `linkauthor`
2. 查不到，才用项目描述搜 Europe PMC（会带出很多"话题相关"的论文）。用作者单位 & 宏基因组关键词过滤：作者/单位对上且含 metagenome 关键词且非 Review / meta-analysis → `high`；否则（无关键词 或 是 Review / meta-analysis）→ `linkauthor`（质量同 low，不进全文）

爬取论文的 标题+摘要/[全文:默认不爬]+paper的其它信息，比如：paper_title / paper_authors / paper_year /journal/pmid/pmcid/doi 

### 2.3 project_fulltext.jsonl （option）

之后应客户要求，再对某些项目进行全文爬取。注意，有些文章不是openAccess，不一定能下载


## 步骤 3  INFERENCE_METHOD

从不同来源的文本，推断想要的信息。
参考两个 INFERENCE_METHOD 里的规则和坑，生成我们自己的 INFERENCE_METHOD ，根据我的指示改

1. 用规则 + 字典从文本推出 `country` / `date` / `host` 等信息。对于每一个推断的值，
    - 记录 `confidence`（上下文含有采集关键词：high/medium）+ `source`（文本来源：study_meta/literature）。对于 `host` 额外 `tax_confidence`（taxa关键词是否都在文本中：high/medium）
    - 记录相关上下文，作为推断的evidence

2. 对于规则判断结果中质量不佳者（从 `confidence` 列表判定。仅 country/host；date 豁免），人工（LLM）阅读 evidence_text，并且回答[xx]信息的值（或依旧无法判断）。强调一下：要的是你（WorkBuddy 代理，本身就是 LLM）直接读 evidence 并推断，不走外部 API。具体来说：用脚本把 evidence 打印你、你一条条读、一条条判，再写入结果文件；**跑的时候注意上下文长度、自动清理，会话里不用报告任何结果（防止上下文过长）、只要保存结果即可 ----- 如果需要判定的量非常大，尝试开 sub agents 加速**

3. 对于以上两步依旧无法判定的，用户会在对话中提供消息，由LLM阅读判定（必要时联网搜索）、规范化至资源文件‘manual_check_[country/data/host].json’）以供复用

4. 合并，优先级A：`confidence` high > medium > low; 保证优先级A的前提下、优先级B：`source` manual > LLM > rule

### 流程示意：infer_host

```bash
infer_host(sources)
│
│  sources = [study_title, study_description, literature_title, literature_abstract]
│
├─ 1. 对每段文本，用 5 类词表匹配（_find_words，词边界+可选复数 s?）
│   ├─ HOST_HUMAN_TRIGGER  → hit_human[]   # "human", "patient", ...
│   ├─ HOST_ANIMAL         → hit_animal[]  # "cattle"→Bos taurus, ...
│   ├─ HOST_ENV            → hit_env[]     # "soil"→soil metagenome, ...
│   ├─ HOST_SITE           → hit_site[]    # "gut", "oral", "lung"(require_human), ...
│   └─ HOST_ANIMAL_SOFT    → hit_soft[]    # "monkey", "shrimp", ...
│
├─ 2. 组合规则，生成所有可能的值（遍历所有命中）
│   │
│   ├─ site 命中（逐 site 词）
│   │   ├─ human + site → "human X metagenome"       # rule_host_human
│   │   ├─ animal + gut site → "X gut metagenome"    # rule_host_animal
│   │   └─ site only → "X metagenome"                # rule_host_env
│   │
│   ├─ human 独立（无 site 时）→ "Homo sapiens"
│   ├─ animal 独立（无 site 时，逐动物）→ "Bos taurus", ...
│   ├─ env（逐 env 词）→ "soil metagenome", "aquatic metagenome", ...
│   └─ soft（须整段含 HOST_CTX）→ "monkey", "shrimp", ...
│
├─ 3. 去重 → unique_vals
│
├─ 4. 逐值 confidence（列表，与 value 对齐）：
│   │   对每个值 v（及其命中片段 snippet）：
│   │   ├─ confidence：snippet 含 CTX_SAMPLE（collected/sampled/...）→ "high"；否则 "medium"
│   │   ├─ tax_confidence（仅 host）：
│   │   │   ├─ method=rule_host_soft → 恒 "medium"
│   │   │   ├─ is_high_evidence(v, method, snippet)：
│   │   │   │   ├─ 规则1：三字名 host词+site词同在 → high
│   │   │   │   ├─ 规则2：二字名 两词同在 → high
│   │   │   │   └─ 拉丁二名法（Bos taurus）→ 恒 medium
│   │   │   └─ 不满足 → medium
│   │   conf_list = ["high", "medium"]
│   │   tax_list  = ["high", "medium"]
│   │   method（列表）：逐值 method；多值可取 "rule_multi_host" 兜底
│   │   evidence = [ {"value":...,"sub_source":...,"snippet":...}, ... ]
│   │   含 soft → needs_review=True
│   └─ 返回 rec
│
└─ 无命中 → None
```



### 流程示意：infer_date

```bash
infer_date(sources)
│
│  sources = [study_title, study_description, literature_title, literature_abstract]
│
├─ 1. 对每段文本，YEAR_RE 抓所有 1900-2099 的 4 位数
│   │   每个命中记录 (年份, sub_source, ±30字片段)
│   │   按年份去重（每年保留第一个命中）
│   │
│   └─ 无命中 → None（unknown）
│
├─ 2. 汇总
│   │   ys = sorted(去重年份)        # [2018, 2020]
│   │   val = ["2018", "2020"]       # 年列表
│   │   method: 单年→rule_date_year  多年→rule_date_range
│   │
│   │   逐值 confidence（列表）：对每个值 v（及其命中片段 snippet）
│   │   ：
│   │   ├─ confidence：snippet 含 CTX_SAMPLE（collected/sampled/...）→ "high"；否则 "medium"
│   │   └─ conf_list = ["high", "medium"]
│   │   method（列表）：单年→["rule_date_year"]  多年→["rule_date_range"]
│   │
│   │   记录级 confidence = "high"（有年份一律 high，不受 value_confidence 影响）
│   │
│   │   evidence = [                          # 结构化列表，每年一段
│   │       {"value":"2018", "sub_source":"study_title", "snippet":"…collected in 2018…"},
│   │       {"value":"2074", "sub_source":"literature_abstract", "snippet":"…2074 genera…"}
│   │   ]
│   │
│   └─ 返回 rec
│
└─ 返回 rec 或 None
```


### 流程示意：infer_country

```bash
infer_country(sources)
│
│  sources = [study_title, study_description, literature_title, literature_abstract]
│
├─ 1. 对每段文本，用 4 类词表匹配（_word_boundary_find，词边界）
│   ├─ DEMONYM    → 国籍形容词→国     # "american"→United States
│   ├─ PLACE      → 地名/国名→国      # "beijing"→China, "germany"→Germany
│   ├─ REGION     → 区域词            # "europe", "pacific"
│   └─ OPEN_OCEAN → 公海/深海         # "open ocean", "abyssal"
│
├─ 2. 汇总判定（优先级：countries > ocean > regions）
│   │
│   ├─ 有国家命中：
│   │   │   vals = sorted(所有抓到的国家)     # ["Cyprus", "Germany"]
│   │   │
│   │   │   逐值 confidence（value_confidence）:
│   │   │   ├─ 对每个国家 c：检查其命中片段是否含 CTX_SAMPLE 词
│   │   │   │   "samples collected from Cyprus" → high
│   │   │   │   "compared to data from Germany" → medium
│   │   │   └─ per_val_conf = {"Cyprus": "high", "Germany": "medium"}
│   │   │
│   │   │   记录级 confidence = 取最高（任一 high → high）
│   │   │
│   │   │   method: 单国→rule_demonym/rule_place  多国→rule_multi_country
│   │   │
│   │   │   evidence = [                          # 结构化列表，每值一段
│   │   │       {"value":"Cyprus",  "sub_source":"study_title", "snippet":"…collected…"},
│   │   │       {"value":"Germany", "sub_source":"literature_abstract", "snippet":"…compared…"}
│   │   │   ]
│   │   │
│   │   └─ 返回 rec
│   │
│   ├─ 无国家但有公海命中（且无区域词）：
│   │   └─ value="NotCountry", confidence="NotCountry"（high 否定判定）
│   │       value_confidence = {"NotCountry": "high"}
│   │
│   ├─ 无国家但有区域词：
│   │   └─ value=["europe","pacific"], confidence=medium
│   │       value_confidence = {"europe": "medium", "pacific": "medium"}
│   │
│   └─ 无命中 → None（unknown）
│
└─ 返回 rec 或 None
```

### 步骤流程

对每个 project_accession，先用规则匹配 （3.1 规则步）

1. 从 study_meta + high 论文 取文本 `build_sources()` 
2. infer_country / infer_host / infer_date
3. 生成一条 rec（如下），写入 <field>_infer.jsonl

```bash
{
    "project_accession": "PRJEB35612",
    "field": "host",
    "value":          ["aquatic metagenome", "soil metagenome"],
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

然后，LLM 复核：
```bash

is_residual(rec)
│
├─ field == date
│   └─ 不进（豁免）
│
├─ confidence 列表为空（规则没抓到值）
│   └─ 进LLM，读原始文本，因为无evidence
│
├─ confidence 列表有值
│   │
│   ├─ 列表全部 high → False（整个项目不进 §3.2）
│   │
│   └─ 列表任一非 high → True（项目进 §3.2）
│      LLM 读整个项目的 evidence_text
│      但只复核非 high 的值：
│           ├─ value[0] confidence=high   → 跳过
│           ├─ value[1] confidence=medium → 读 evidence[1]，判
│           └─ value[2] confidence=low    → 读 evidence[2]，判
│
└─ 返回 True/False
```

