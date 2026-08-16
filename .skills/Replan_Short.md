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
    - **输出值格式（折射保留）**：值 = `映射值:折射前原值`，下游匹配只看冒号前。country 子地名→`Country:Place`（Japan:Tokyo）；date 每年最细粒度 `YYYY-MM-DD`/`YYYY-MM-XX`/`YYYY-XX-XX`；host→`pig gut metagenome:Sus scrofa`（原词已含在值中则不加）；open_ocean→`NotCountry:命中关键词`（如 `NotCountry:open ocean`），region 值即命中词本身故无后缀（2026-08-13 改，未重跑）

2. LLM 推断：对所有有可信论文的项目，你（WorkBuddy 代理，本身就是 LLM）**一次读入该项目全部 evidence，同判 country/date/host 三字段**，并在同一次读取里**先做论文主题甄别**（不符主题的 high 论文标 `aligned=false`，后续降级 candidate）。LLM 结果写**独立文件**（不覆盖 §3.1 规则输出），两者一致性由 reconcile 核对。
    - 强调：要你直接读 evidence 推断，**不走外部 API**。脚本把 evidence 打印你、你一条条读、一条条判，再写入结果文件；**跑的时候注意上下文长度、自动清理，会话里不用报告任何结果（防止上下文过长）、只要保存结果即可 ----- 如果需要判定的量非常大，尝试开 sub agents 加速**
    - 默认只判有 high 论文的项目（`--scope high-paper`）；可选把无 high 论文的项目（`--scope no-high-paper` ，evidence 仅 study_meta）也判，结果写同一套文件。
    - **判定格式约定见脚本常量 `JUDGE_SPEC`**（与规则对齐：country 有地点→`Country:Place`；date 最细粒度+XX 占位；host 对齐 taxid_type 词表、**不加 :orig 后缀**）。起判定代理时原样嵌入指令。

3. 对于以上两步依旧无法判定的，用户会在对话中提供消息，由LLM阅读判定（必要时联网搜索）、规范化至资源文件‘manual_check_[country/data/host].json’）以供复用

4. 合并：先在 §3.2 内做**规则×LLM reconcile**（比较前规则值剥 `:后缀`、date 用 XX 通配；agree→high；仅一方→取该方；disagree 且置信相当→flag review；disagree 分高低→取高置信方），再由 §3.4 final_merge 把 manual 并入。final_merge：**manual 优先；无 manual 取 LLM 值**；LLM 值字面包含于规则值列表→标 `consistent`，否则标 `conflict` 并送 LLM 裁决语义等价（等价→改标 consistent，仍取 LLM；真不同→保持 conflict）。

> 规则三函数（infer_country/infer_date/infer_host）与 §3.2 四阶段的流程示意见 **auto.explain3.md**。


## 步骤 4 Clean metagenomic_wgs.typed.csv 


我们已经得到了 final_{country/date/host}.jsonl，这些 project级 信息可以作为清洗 metagenomic_wgs.typed.csv 的参考

-------------------------------
```bash
提取 metagenomic_wgs.typed.csv 的 run_accession · sample_accession · project_accession · country · location 至 tmp.country.csv    
tmp.country.csv，依照 project_accession 从 final_country.jsonl 的 （value，confidence，source，method，note, decided_by, consistency） 字段增加相应 ‘infer_[]’ 列    

对所有 infer_value 的 NotCountry 值，仅依据值描述本身判断类别：描述指向跨国/全球聚合或海洋/公海（含边界地理实体）则保留，否则（明确包含"无地理位置信息"类）清空；不使用项目 evidence note 做兜底匹配。

**然后，看看 infer 对原表country字段补足了多少？有多少原表有信息但infer无？重合的部分里，有多少与原表一致、有多少与原表冲突**

对于country的冲突条目，请逐行检查是写法不一还是真实冲突；然后对于这些真矛盾的项目：聚合每个项目的原国家分布（按总表）、项目级 infer 值、以及误判来源
```
-------------------------------
```bash
提取 metagenomic_wgs.typed.csv 的 run_accession · sample_accession · project_accession · collection_date · first_public 至 tmp.date.csv   
tmp.host.csv，依照 project_accession 从 final_host.jsonl 的 （value，confidence，source，method，note, decided_by, consistency） 字段增加相应 ‘infer_[]’ 列    

对于所有 infer_value ， 将 NotDate 值设定为空。注意，如果infer是多值的话，它对应的是个采样区间（最早-最晚，而且日期都应该不晚于2026年8月1日）。

**然后，看看 infer 对原表collection_date字段补足了多少？有多少原表有信息但infer无？重合的部分里，有多少与原表一致（包括：原表年份落在infer的区间）、有多少与原表冲突**，注意原表中 零值占位符 '0000-00-00' 等异常值应视为缺失

对于collection_date真年份冲突条目所对应的项目：聚合每个项目的原日期分布（按总表）、项目级 infer 值、冲突类别、冲突值来自LLM还是rule

对于 原表，告诉我时间跨度 ≥10 年 或者 ≥5 年 的项目有多少、这些项目都是研究什么的（类别、数量、含义 / 典型研究）？有多少是真的长跨度、有哪些可能是某个样本标错（比如：样本年份的分布是不是有离群值）

对于 infer_value，告诉我时间跨度 ≥10 年 或者 ≥5 年 的项目有多少、都是研究什么的？
```
-------------------------------
```bash
提取 metagenomic_wgs.typed.csv 的 run_accession · sample_accession · project_accession · type · scientific_name · tax_id · host · host_tax_id 至 tmp.host.csv   
tmp.date.csv，依照 project_accession从 final_date.jsonl 的 （value，confidence，source，method，note, decided_by, consistency） 字段增加相应 ‘infer_[]’ 列   
tmp.date.csv 增加 ‘first_paper_year’ 和 ‘first_paper_title’，记录最早发表的 `high` paper 的时间和title   

对于所有 infer_value ， 将 infer 无/NotHost 值设定为空

**然后，看看 infer 对原表scientific_name字段补足了多少？有多少原表有信息但infer无？重合的部分里，有多少与原表一致、有多少与原表冲突**

对于host的冲突条目，请逐行检查是写法不一还是真实冲突；然后对于这些真矛盾的项目：聚合每个项目的原host分布（按总表）、项目级 infer 值、以及误判来源
```

-------------------------------

对每个 tmp.{}.csv 新增两列 'selected_value'（优先选择原值，无原值则用infer_value插补，遵循'three_dim_fill_safety_table.md'的建议） 和 'selected_value_source' （标注：ori_value/infer_value），结果保存至 {}.csv

另外，告诉我：用infer_value插补的run中，有多少是单值、有多少是区间 ？ 注意，统计country时，不是按结构口径（一个单元格 = 一个值），而是按"值实际代表几个国家/地理实体"的语义口径看