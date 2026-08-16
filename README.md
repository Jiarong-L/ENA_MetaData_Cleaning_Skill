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


## Result Stat


对比原表和infer_value之间的冲突条目，冲突条目的状况请参考 [conflict_types.md (AI generated)](./Result_20100101_20260801/stat/conflict_types.md)，如果用 infer_value 填补原表缺失的话可能会引入这些错误（我们暂时认为原表是准确值 & 忽略写法、粒度差异）


| 维度 | 重合项目（/所有） | 冲突项目(/重合) | 重合run（/所有） | 冲突run(/重合) | 可补缺(/所有) | 语义一致? | 可否安全补 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Country** | 12,796（45.2%） | 1,530（12.0%） | 205,019（16.4%） | 62,486（30.5%） | 10.7%（133,082 / 1,248,145） | 是（同本体，归一化可比；但 run 级 30.5% 为真实异国冲突） | ⚠️ 条件安全：仅对非冲突项目（11,266/12,796=88%）补缺；排除 742 真实误判（fully_disjoint 624 + incomplete_subset 116 + other 2），notcountry_kept 788 为保留决策、非误判、无需排除 |
| **Host** | 3,983（14.1%） | 129（3.2%） | 246,120（19.7%） | 4,630（1.9%） | 30.8%（384,287 / 1,248,145） | 否（物种名 vs 生境/部位描述，不同本体） | ⚠️ 条件安全：需语义转换（infer 填 host 会改变语义，只适合当 "host environment"） |
| **Date** | 2,210（7.8%） | 271（12.3%） | 23,269（1.9%） | 6,154（26.4%） | 4.8%（59,406 / 1,248,145） | 是（同本体，但精度常仅年/XX） | ⚠️ 低价值+谨慎：覆盖仅 4.8% 且精度有限，仅应补非冲突项目空缺并标 low-confidence |


另外，我们查看了一些 metadata（原值）中显示时间跨度非常长的项目，发现一些离群值疑似标错，留待人工确认： [date.span_orig.md (AI generated)](./Result_20100101_20260801/stat/date.span_orig.md)


## Use it

TBA

