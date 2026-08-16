# ENA_MetaData_Cleaning_Skill
for  METAGENOMIC (WGS) only

只适用于 METAGENOMIC (WGS) run 的元数据


## Limits

1. 流程经多轮AI交互修改后，其细节实际上已经变得混乱且难以阅读，建议只看 [Replan_Short.md](./.skills/Replan_Short.md) 了解一下我大致做了什么

2. 规则设计效果不佳，因此目前我设定最终结果优先选取来自LLM的推断
    - 3.2 中 reconcile 仅作为 QA 报告（规则 vs LLM），不跑这一步也不会影响 final 输出 （`final_{country/date/host}.jsonl`）

3. 目前的信息源不包含全文，因此许多信息无法推断，比如：采样时间和地点的描述很可能位于原文的Method部分。 同时，这样导致 LLM 在判定（Study Description & Paper Abstruct）主题相关性的时候过于严格，将关联论文也标注 `"aligned": false`，见 [agent_paper_verdicts.jsonl](./Result_20100101_20260801/agent_paper_verdicts.jsonl)

4. 由于流程的设计缺陷，来自 `"aligned": false` 论文的推断依旧保留在结果中（不仅仅是过于严格而被错标的那些）


ToDo：或许我可以将LLM的推断结果用作训练标签，重新设计匹配规则。但在此之前，我应该重新检查当前的LLM判定格式约定`JUDGE_SPEC`


## Result


对比原表和infer_value之间的冲突条目，冲突条目的状况请参考 [conflict_types.md (AI generated)](./Result_20100101_20260801/stat/conflict_types.md)，如果用 infer_value 填补原表缺失的话可能会引入这些错误（我们暂时认为原表是准确值 & 忽略写法、粒度差异）



另外，我们查看了一些 metadata（原值）中显示时间跨度非常长的项目，发现一些离群值疑似标错，留待人工确认： [date.span_orig.md (AI generated)](./Result_20100101_20260801/stat/date.span_orig.md)









## Use it

TBA

