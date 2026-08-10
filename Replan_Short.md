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
搜索关联论文，为 PaperSource 标注置信来源（`papersource`：high/low/missing）

1. 先用项目编号查 Europe PMC（最准，指名道姓: high quality）
2. 查不到，才用项目描述搜 Europe PMC（会带出很多"话题相关"的论文）。用作者单位&宏基因组关键词过滤

爬取论文的 标题+摘要/[全文:默认不爬]+paper的其它信息，比如：paper_title / paper_authors / paper_year /journal/pmid/pmcid/doi 

### 2.3 project_fulltext.jsonl （option）

之后应客户要求，再对某些项目进行全文爬取。注意，有些文章不是openAccess，不一定能下载


## 步骤 3  INFERENCE_METHOD

从不同来源的文本，推断想要的信息。
参考两个 INFERENCE_METHOD 里的规则和坑，生成我们自己的 INFERENCE_METHOD ，根据我的指示改

1. 用规则 + 字典从文本推出 `country` / `date` / `host` 等信息
    - 提供两个质控标注（二者不会相互影响）：匹配内容本身的可信度 & 文本来源（study_meta/literature_{title/}）
    - 记录相关上下文，作为推断的evidence

2. 对于规则匹配不仅（仅指：匹配内容本身的可信度，先不管来源）
    - 人工（LLM）阅读 evidence_text，并且回答[xx]信息的值（或依旧无法判断）。强调一下：要的是你（WorkBuddy 代理，本身就是 LLM）直接读 evidence 并推断，不走外部 API。具体来说：用脚本把 evidence 打印你、你一条条读、一条条判，再写入结果文件；跑的时候注意上下文长度、自动清理，会话里不用报告任何结果（防止上下文过长）、只要保存结果即可 ----- 如果需要判定的量非常大，尝试开 sub agents 加速

3. 对于以上两步依旧无法判定的，用户会在对话中提供消息，由LLM阅读判定（必要时联网搜索）、规范化至资源文件‘manual_check_[country/data/host].json’）以供复用

4. 合并，优先级A：`confidence` high > medium > low; 保证优先级A的前提下、优先级B：`source` manual > LLM > rule


## 步骤 4  

现在，这些 project级 信息可以作为清洗 raw.metagenomic_wgs.csv 的参考

### 4.1 


对于 raw 中的每一条 Run，我们先核验：

1. 看看有多少 





