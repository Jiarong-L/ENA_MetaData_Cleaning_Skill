
## 步骤 3  INFERENCE_METHOD

对每个 project_accession，先用规则匹配 **（3.1 规则步）**

1. 从 study_meta + high 论文 取文本 `build_sources()` 
2. infer_country / infer_host / infer_date
3. 生成一条 rec（如下），写入 <field>_infer.jsonl

```bash
{
    "project_accession": "PRJEB35612",
    "field": "host",
    "value":          ["aquatic metagenome:water", "soil metagenome"],  ← 值 = 映射值:折射前原值（原词已含在映射值中则不加，如 soil）；匹配只看冒号前
    "confidence":     ["medium", "medium"],      ← CTX_SAMPLE：命中片段是否含采集词 ("collected from...")
    "tax_confidence": ["medium", "medium"],      ← is_high_evidence：host 专属，Taxa的推断是否合理（比较前剥 :后缀）
    "source":         ["study_meta", "study_meta"],
    "method":         ["rule_host_env", "rule_host_env"],
    "evidence": [
        {"value": "aquatic metagenome:water", "sub_source": "study_title", "snippet": "…irrigation water in microbiomes…"},
        {"value": "soil metagenome",          "sub_source": "study_title", "snippet": "…of soil and Lactuca Sativa…"}
    ],
    "matched_tokens": [["water"], ["soil"]]
}
```

然后，LLM 平行复核 **（3.2 LLM步）**。注意：进LLM = LLM 一次读整个项目的 evidence_text（study_meta + 全部 high 论文），同判三字段。

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
│            输出遵循 JUDGE_SPEC（脚本常量，起代理时原样嵌入指令）：
│              country 有城市/地点 → 'Country:Place'；date 最细粒度
│              YYYY-MM-DD/YYYY-MM-XX/YYYY-XX-XX（禁裸 YYYY）；
│              host 对齐 taxid_type 词表、不加 :orig 后缀
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
            比较前规则值先剥 ':折射前' 后缀（_base_val，只看冒号前）
            date 用 XX 通配段比较（_dates_compatible：2019-XX-XX 兼容 2019-03-15）
            agree(取值集合相交)     → 并集 + high
            仅一方有值            → 取该方
            disagree 且置信相当    → flag review（暂定，暂取规则值）
            disagree 置信分高低    → 取高置信方
            双方 unknown          → unknown
            → reconciled_<field>.jsonl + review_<field>.jsonl
```

完成后，再由 §3.4 final_merge 把 manual 并入成三源终态：
```bash
对每个字段每个项目:
  if manual 有值: final_value = manual 值      # 用户背书，最高档
  else:
      final_value = LLM 值                      # 优先取 LLM
      if LLM值 ⊆ 规则值(字面, 规则先剥:后缀): label = consistent
      else:
          if LLM值 ⊆ 规则值(轻量归一后): label = consistent   # 可选预过滤
          else: 送 LLM 裁决
                  ├ 语义等价 → label = consistent (仍取 LLM)
                  └ 真不同   → label = conflict    (仍取 LLM)
```

> 注：`ena_final_merge.py` 目前仍是旧「双轴优先级」实现且读 `agent_llm_<field>.jsonl`
> （平行架构不产出该文件），需按上述政策重写后方可使用。



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
│   │   所有值经 _with_orig(映射值, 原词) 加 ':折射前原值' 后缀（原词已含在映射值中则不加）
│   │   ├─ 有人源 + 该 site 有 human_name → "human X metagenome[:site原词]" (rule_host_human)
│   │   ├─ 否则：动物俗名 + site∈GUT_SITE + 动物∈ANIMAL_GUT_NAME
│   │   │        → "X gut metagenome:物种学名" (rule_host_animal)
│   │   │          例：pig gut metagenome:Sus scrofa
│   │   ├─ 否则：generic 且非 require_human → "X metagenome"
│   │   │        （有人源→rule_host_human，无→rule_host_env）
│   │   └─ require_human 但无人源 → 不妄判，跳过（留 §3.2）
│   │
├─ 2. 无 site 时，human/animal 独立成值（仅当 hit_site 为空）
│   │   ├─ 有人源 → "Homo sapiens[:触发词]" (rule_host_human)
│   │   └─ 每个动物 → "物种学名[:俗名]" (rule_host_animal)（同名则不加后缀）
│   │
├─ 3. env 命中（每个 env 词一个值，与 site 无关）
│   │   对每个 hit_env → "X metagenome[:env原词]" (rule_host_env)
│   │   例：marine metagenome:ocean；soil metagenome（soil 已含在值中，不加）
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
    │   │                  is_high_evidence(v,method,snippet)？（v 先剥 :后缀）
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
├─ 1. 扫描所有文本，三级正则（限 1900<=y<=2100）
│   │   对每个 (sub_source, text)：
│   │   ├─ DATE_FULL_RE  YYYY-MM-DD（分隔符 -/.）→ gran 3
│   │   ├─ DATE_YM_RE    YYYY-MM                → gran 2
│   │   └─ YEAR_RE       YYYY                   → gran 1
│   └─ 无命中 → return None（交 blank_record / §3.2 补漏）
│
├─ 2. 按年聚合，每年保留最细粒度（gran 3>2>1 只升不降）
│   │   value 形态：完整 → "YYYY-MM-DD"；缺日 → "YYYY-MM-XX"；缺月 → "YYYY-XX-XX"
│   ys = 排序后的唯一年份列表
│
└─ 3. 逐值组装（每年一个值，与 value 对齐）
    │   method 固定 "rule_date"（所有年份同，不再分单年/范围）
    │   对每个年份 y：
    │   ├─ value:          "2019-03-15" / "2019-03-XX" / "2019-XX-XX"
    │   ├─ confidence:     该年片段含 CTX_SAMPLE？ high : medium
    │   │                  "samples collected in 2018" → high
    │   │                  "2074 genera constituted"   → medium
    │   ├─ source:         study_meta / literature
    │   ├─ method:         "rule_date"
    │   ├─ evidence:       {"value":v, "sub_source":…, "snippet":…}
    │   └─ matched_tokens: [v]
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
│   │   ├─ PLACE（国名/地名 cyprus→Cyprus）     → countries[out_v] += rule_place
│   │   │     子地名折射：命中词≠国名本身 → out_v = "Country:Place"
│   │   │     （tokyo→"Japan:Tokyo"；uk→"United Kingdom:UK"；china→"China" 不加）
│   │   ├─ REGION（区域词 europe/pacific）       → regions[word]
│   │   └─ OPEN_OCEAN（公海/深海）               → ocean.append(…)
│   │
├─ 2. 分支判定（优先级 countries > ocean > regions > None）
│   │
│   ├─【A】countries 非空（最常见）── 逐值组装
│   │   │   vals = 排序后的值列表（国名 或 Country:Place）；对每个值 c：
│   │   │   ├─ value:          c（如 "Japan" / "Japan:Tokyo"）
│   │   │   ├─ confidence:     c 任一命中片段含 CTX_SAMPLE？ high : medium
│   │   │   │                  "collected from Cyprus"         → high
│   │   │   │                  "compared to data from Germany" → medium
│   │   │   ├─ source:         study_meta / literature
│   │   │   ├─ method:         rule_demonym / rule_place（逐值，无 rule_multi_country）
│   │   │   ├─ evidence:       {"value":c, …}
│   │   │   └─ matched_tokens: 该值命中原始词集合 [["cyprus","cypriot"]]
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
