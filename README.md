# ENA_MetaData_Cleaning_Skill
for  METAGENOMIC (WGS) only

只适用于 METAGENOMIC (WGS) run 的元数据


## Limits

1. 流程经多轮AI交互修改后，其细节实际上已经变得混乱且难以阅读，建议只看 [Replan_Short.md](./.skills/Replan_Short.md) 了解一下我大致做了什么

2. 规则设计效果不佳，因此目前我设定最终结果优先选取来自LLM的推断
    - 3.2 中 reconcile 仅作为 QA 报告（规则 vs LLM），不跑这一步也不会影响 final 输出 （`final_{country/date/host}.jsonl`）

3. 目前的信息源不包含全文，因此许多信息无法推断，比如：采样时间和地点的描述很可能位于原文的Method部分。 同时，这样导致 LLM 在判定（Study Description & Paper Abstruct）主题相关性的时候过于严格，将关联论文也标注 `"aligned": false`，见 [agent_paper_verdicts.jsonl](./Result_20100101_20260801/agent_paper_verdicts.jsonl)

4. 由于流程的设计缺陷，来自 `"aligned": false` 论文的推断依旧保留在结果中（不仅仅是过于严格而被错标的那些）


ToDo：或许我可以将LLM的推断结果用作训练标签，重新设计匹配规则。但在此之前，我应该重新检查当前的LLM判定格式约定`JUDGE_SPEC`，或许我一开始就应该参考 [FAIRy ENA Rulepacks](https://github.com/yuummmer/fairy-rulepacks-insdc)，而且我需要限制 LLM-agent 过度发散的臆测（见下文 conflict_types）

ToDo：我还需要规范化一下每个字段的值，现在它们还不可以直接用


## Result Stat

对比原表和infer_value之间的冲突条目，冲突条目的状况请参考 [conflict_types.md (AI generated)](./Result_20100101_20260801/stat/conflict_types.md)，如果用 infer_value 填补原表缺失的话可能会引入这些错误（我们暂时认为原表是准确值 & 忽略写法、粒度差异）


| 维度 | 重合项目（/所有） | 冲突项目(/重合) | 重合run（/所有） | 冲突run(/重合) | 可补缺(/所有) | 语义一致? | 可否安全补 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Country** | 12,652（44.7%） | 1,388（11.0%） | 202,499（16.2%） | 59,984（29.6%） | 133,328（10.7%） | 是（同本体，归一化可比；run 级 29.6% 为真实异国冲突） | ⚠️ 条件安全：仅对 133,328 可补缺 run 中落在非冲突项目的 121,729（91.3%）填充；冲突项目内 11,599（8.7%）不补 |
| **Host** | 3,983（14.1%） | 129（3.2%） | 246,120（19.7%） | 4,630（1.9%） | 384,287（30.8%） | 否（物种名 vs 生境/部位描述，不同本体） | ⚠️ 条件安全+需语义转换：仅对 384,287 可补缺 run 中落在非冲突项目的 380,990（99.1%）填充；冲突项目内 3,297（0.9%）不补（且 infer 生境/部位描述只适合当 "host environment"） |
| **Date** | 2,326（8.2%） | 339（14.6%） | 28,842（2.3%） | 10,359（35.9%） | 53,905（4.3%） | 是（同本体，但精度常仅年/XX） | ⚠️ 低价值+谨慎：仅对 53,905 可补缺 run 中落在非冲突项目的 53,641（99.5%）填充；冲突项目内 264（0.5%）不补 |


合并后：

| 文件 | ori_value（保留原值） | infer_value（非冲突项目插补） | blank（未补） |
| --- | --- | --- | --- |
| [country.csv](./Result_20100101_20260801/stat/country.csv.gz) | 914,652 | 121,729 | 211,764 |
| [host.csv](./Result_20100101_20260801/stat/host.csv.gz) | 472,925 | 380,990 | 394,230 |
| [date.filtered.csv](./Result_20100101_20260801/stat/date.filtered.csv.gz) | 813,580 | 53,641 | 380,924 |


有一点需要注意，来自项目信息的 infer_value 可以是多值，会影响一些插补：

| 文件 | infer_value 插补总数 | 单值 | 合集/多值 |
| --- | --- | --- | --- | --- |
| **country.csv** | 121,729 | **71,570**（语义单实体） | 0 | **50,159**（多国/全球） |
| **host.csv** | 380,990 | 347,018 | 33,972 |
| **date.filtered.csv** | 53,641 | 46,884 | 6,757 |


另外，我们查看了一些 metadata（原值）中显示时间跨度非常长的项目，发现一些离群值疑似标错，留待人工确认： [date.span_orig.md (AI generated)](./Result_20100101_20260801/stat/date.span_orig.md)


## See Data

查看 {country/host/date}.csv 的 selected_value 列，所有的项目中，有多少项目是跨宿主、跨地域、跨时间的？分别列出






