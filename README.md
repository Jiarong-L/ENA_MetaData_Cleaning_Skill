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

对比原表和infer_value之间的冲突条目。对于冲突的条目，我们暂时以原表为主，但需要人工查看一下情况。

* country：忽略写法、粒度差异，真实冲突样本所属的项目 [country.realconflict_projects.csv](./Result_20100101_20260801/stat/country.realconflict_projects.csv) 提示: `fully_disjoint` 错误可能来自 `study_meta-rule_` 、错误的literature匹配（有15个关联了 `"aligned": false`的论文）、LLM-agent 过度发散的臆测（约占四分之三）



* date：绝大多数infer_value是幻觉年份，因此或许不能过于相信用它补足的原表。[date.genuine_conflict_projects.csv](./Result_20100101_20260801/stat/date.genuine_conflict_projects.csv)





* host：[host.realconflict_projects.csv](./Result_20100101_20260801/stat/host.realconflict_projects.csv)
















## Use it

TBA

