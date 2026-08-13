#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.2-parallel：LLM 与规则平行的一级推断器（替代「残差路由」设计）。

设计（2026-08-13 与用户定案）：
  - 不再有 is_residual 路由层。LLM 对「有可信证据的项目」与 §3.1 规则**平行**，
    一次读入该项目的全部 evidence，**同时判 (country, date, host) 三字段**。
  - evidence = study_title + study_description + 该项目所有 high 论文的标题/摘要。
    **不含** §3.1 规则输出（保持 LLM 独立，规则留作 reconcile 阶段的交叉验证，避免锚定）。
  - LLM 结果写入**独立文件**（ena_llm_infer_<field>.jsonl），不覆盖 §3.1 输出。
  - reconcile 阶段再把 §3.1 规则 与 §3.2 LLM 按字段合并（agree/unknown/flag-review）。

本脚本不判值，只负责 I/O、归一、reconcile。"你"（WorkBuddy 代理，本身是 LLM）读
evidence → 逐项目判三字段 → 写判定文件。会话内只落盘、不打印 evidence（防上下文膨胀）。

阶段：
  batch     按 --scope 选项目，每项目拼一份共享 evidence_text，写 agent_parallel.jsonl。
            evidence 里每篇 high 论文**独立分块并标注 pid**（[paper #n | pid=...]），
            供 LLM 逐篇判主题并映射降级。支持断点续跑。只打印摘要。
  merge     读代理写好的 agent_llm_parallel.jsonl（每行=一项目，含 papers 主题裁决 +
            country/date/host 三个子判定），按字段归一并**分写** ena_llm_infer_{country,date,
            host}.jsonl；同时把 papers 裁决写入 agent_paper_verdicts.jsonl。只打印统计。
  apply-demote  读 agent_paper_verdicts.jsonl，把 aligned=false 的论文在 literature 里
            high→candidate（幂等，首次备份到 _bak/project_literature.pre_demote.jsonl，
            之后从备份重算）。§3.1 只读 high → 被降级论文自动不再消费。
  reconcile 对每字段，合并 §3.1 规则 + §3.2 LLM：
              比较前规则值先剥 ':折射前' 后缀（_base_val，规则匹配只看冒号前）；
              date 的 agree 用 XX 通配段比较（_dates_compatible，
              如 '2019-XX-XX' 兼容 '2019-03-15'）
              agree(取值集合相交)      → 并集，confidence=high，method=agree
              仅一方有值               → 取该方
              disagree 且置信相当      → **flag review**（暂定，needs_review=True，暂取规则值）
              disagree 且置信分高低    → 取高置信方，method=disagree_<winner>
              双方均 unknown           → unknown
            写 reconciled_<field>.jsonl + review_<field>.jsonl + reconcile_stats.json。

代理一次读取要完成两件事（对应用户的「先甄别主题、再判三字段」）：
  ① 对每篇 high 论文判「与 study 主题是否相符」：不符 → aligned=false（该论文将被降级，
     判三字段时不得再以它为据，此时该项目的有效证据只剩 study_meta + 相符论文）。
  ② 在「study_meta + 相符论文」的证据上判 country/date/host。

scope（--scope，默认 high-paper）：
  high-paper      有 ≥1 篇 high 论文的项目（本区间 467 个）——证据最足、LLM 增益最大。
  no-high-paper   【可选补充档，默认不开】没有 high 论文的项目（~1539），evidence 仅 study_meta；
                  结果同样写入 ena_llm_infer_<field>.jsonl（与 high-paper 项目不相交、按 acc 去重）。
  all             study_meta ∪ literature 的全部项目（2006，含薄证据，多半判 unknown）。
  union           high-paper ∪ 任一字段被 is_residual 判为残差的项目（兼顾捞 unknown）。

代理判定文件 agent_llm_parallel.jsonl 每行一条：
  {"project_accession": "PRJ...",
   "papers":  [{"pid":"<pmid>", "aligned": true|false, "note": "..."}],   # 主题甄别
   "country": {"value":[...], "confidence":[...], "note": "..."},
   "date":    {"value":[...], "confidence":[...], "note": "..."},
   "host":    {"value":[...], "confidence":[...], "tax_confidence":[...], "note": "..."}}
  papers：对每篇 high 论文给 aligned（与 study 主题是否相符）；aligned=false 将被降级。
  各字段 value/confidence(/tax_confidence) 为逐值对齐列表；无把握 → value=[] 或 ["unknown"]。
  country 不适用（公海）→ value=["NotCountry"]。

判定格式约定（2026-08-13 用户定，与 §3.1 规则输出对齐）：见下方 JUDGE_SPEC 常量——
  起判定代理时须把 JUDGE_SPEC 原样放进其指令（单一事实源，勿转述改写）。
"""
import os
import json
import shutil
import argparse
from collections import Counter
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPLAN_ROOT = os.path.dirname(SCRIPT_DIR)  # .replan
DEF_OUT = os.path.join(REPLAN_ROOT, ".tmp")
LOG_DIR = os.path.join(REPLAN_ROOT, ".log")

FIELDS = ("country", "date", "host")
_CONF_DOMAIN = {"high", "medium", "low", "unknown", "NotCountry"}
_TAX_DOMAIN = {"high", "medium", "unknown"}  # host tax_confidence 值域（LLM 写 low 归一为 medium）
_TIER = {"high": 3, "NotCountry": 3, "medium": 2, "low": 1, "unknown": 0}

# 判定格式约定（2026-08-13 用户定：LLM 与 §3.1 规则输出对齐）——起判定代理时
# 把本块原样放进其指令（单一事实源，勿转述改写）。
JUDGE_SPEC = """\
判定输出格式约定（与规则层 §3.1 对齐，逐条遵守）：
1. country：INSDC 国名（Japan / United States / China ...）。证据明确提到城市/州/具体地点时，
   用 'Country:Place' 保留地点细节（如 Japan:Tokyo、United States:California、
   United Kingdom:London；Place 首字母大写）——对齐 typed.csv 的 'X: detail' 约定。
   公海/无主权适用 → ["NotCountry"]。
2. date：尽量给最细粒度——有完整日期 'YYYY-MM-DD'；只知到月 'YYYY-MM-XX'；
   只知到年 'YYYY-XX-XX'。不要写裸 'YYYY' 或 'YYYY-MM'。
3. host：value 须对齐 taxid_type.tsv 中 is_metagenome=1 的 scientific_name，词表内尽量选最具体者：
   生境 → 'X metagenome'（soil/marine/freshwater ...）；人+部位 → 'human X metagenome'；
   动物+肠道 → 'X gut metagenome'（pig/bovine/mouse gut metagenome ...，X 用词表中已有的 ENA 名）；
   仅部位无归属 → 'gut/oral/skin/vaginal metagenome'；仅人 → 'Homo sapiens'；
   词表无对应 ENA 名的动物/宿主 → 物种学名（如 Macaca mulatta）。
   **不要**给 host 值加 ':orig' 后缀（那是规则层的词典折射标记，LLM 无折射、不用）。
4. 各字段 value/confidence(/tax_confidence) 为逐值对齐列表；无把握 → value=[] 或 ["unknown"]。
"""


def _replan_log(msg):
    """追加一行运行日志到 .log/run_YYYY-MM-DD.log（失败静默）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        lp = os.path.join(LOG_DIR, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        with open(lp, "a", encoding="utf-8") as _f:
            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass


# ---- 输入加载 -------------------------------------------------------------

def load_jsonl_by_acc(path):
    recs = {}
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            acc = d.get("project_accession")
            if acc:
                recs[acc] = d
    return recs


def load_study_meta(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_literature(path):
    """acc -> rec（含 papers[]）。"""
    return load_jsonl_by_acc(path)


# ---- 残差判定（仅 union scope 用） ---------------------------------------

def is_residual(rec):
    if rec is None or rec.get("field") not in ("country", "host"):
        return False
    conf_list = rec.get("confidence", [])
    if isinstance(conf_list, str):
        conf_list = [conf_list]
    conf_list = [c for c in conf_list if c not in (None, "")]
    if not conf_list:
        return True
    return any(c not in ("high", "medium", "NotCountry") for c in conf_list)


# ---- evidence 组装（三字段共享，不含规则输出） ---------------------------

def _paper_pid(p):
    """论文稳定标识：优先 pmid，退 pmcid/doi，再退 title 前缀。"""
    for k in ("pmid", "pmcid", "doi"):
        v = p.get(k)
        if v not in (None, ""):
            return str(v)
    return "t:" + (p.get("title") or "")[:40]


def build_evidence(acc, study_meta, lit_rec, cap_desc=2000, cap_abs=1200, max_papers=5):
    """拼一份供 LLM 直读的 evidence_text：study 标题/描述 + 每篇 high 论文独立分块(带 #序号+pid)。
    返回 (evidence_text, paper_refs)；paper_refs=[{"ref":"#1","pid":"..."}] 供降级映射。"""
    parts = []
    refs = []
    study = study_meta.get(acc, {})
    title = (study.get("study_title") or "").strip()
    desc = (study.get("study_description") or "").strip()
    if title:
        parts.append(f"[study_title] {title}")
    if desc:
        parts.append(f"[study_description] {desc[:cap_desc]}")
    if lit_rec:
        n = 0
        for p in lit_rec.get("papers", []):
            if p.get("papersource") != "high":
                continue
            if n >= max_papers:
                break
            n += 1
            pid = _paper_pid(p)
            refs.append({"ref": f"#{n}", "pid": pid})
            t = (p.get("title") or "").strip()
            ab = (p.get("abstract") or "").strip()
            parts.append(f"[paper #{n} | pid={pid}]")
            if t:
                parts.append(f"title: {t[:300]}")
            if ab:
                parts.append(f"abstract: {ab[:cap_abs]}")
    return "\n".join(parts), refs


def select_scope(scope, study_meta, lit, infers):
    """返回该 scope 下的 project_accession 列表（排序）。"""
    high_paper_accs = {
        acc for acc, rec in lit.items()
        if any(p.get("papersource") == "high" for p in rec.get("papers", []))
    }
    if scope == "high-paper":
        return sorted(high_paper_accs)
    if scope == "no-high-paper":
        # 可选补充档（默认不开）：没有 high 论文的项目，evidence 仅 study_meta。
        all_accs = set(study_meta.keys()) | set(lit.keys())
        return sorted(all_accs - high_paper_accs)
    if scope == "all":
        return sorted(set(study_meta.keys()) | set(lit.keys()))
    if scope == "union":
        resid = set()
        for f in FIELDS:
            for acc, rec in infers.get(f, {}).items():
                if is_residual(rec):
                    resid.add(acc)
        return sorted(high_paper_accs | resid)
    raise ValueError(f"unknown scope: {scope}")


# ---- 阶段：batch ----------------------------------------------------------

def phase_batch(args):
    out = args.out_dir
    study_meta = load_study_meta(args.study_meta)
    lit = load_literature(args.literature)
    infers = {f: load_jsonl_by_acc(args.infer_country if f == "country"
                                   else args.infer_date if f == "date"
                                   else args.infer_host) for f in FIELDS}

    accs = select_scope(args.scope, study_meta, lit, infers)

    # 断点续跑：已判过的 project 跳过
    done = set()
    for p in [os.path.join(out, "agent_llm_parallel.jsonl")] + \
             [os.path.join(out, f"ena_llm_infer_{f}.jsonl") for f in FIELDS]:
        done |= set(load_jsonl_by_acc(p).keys())

    residual = []
    skipped = 0
    for acc in accs:
        if acc in done:
            skipped += 1
            continue
        ev, refs = build_evidence(acc, study_meta, lit.get(acc))
        if not ev.strip():
            _replan_log(f"[batch] {acc}: empty evidence, skipped")
            continue
        residual.append({"project_accession": acc, "papers": refs, "evidence_text": ev})

    out_path = os.path.join(out, "agent_parallel.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for d in residual:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"[batch] scope={args.scope}")
    print(f"  候选项目         : {len(accs)}")
    print(f"  已完成(跳过)     : {skipped}")
    print(f"  待判(本次)       : {len(residual)}  ->  {out_path}")
    print(f"  下一步: 代理读 agent_parallel.jsonl 逐项目判三字段，写 agent_llm_parallel.jsonl，再跑 --phase merge")
    return out_path


# ---- 归一（逐字段） -------------------------------------------------------

def _as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return list(x)
    return [x]


def _align(lst, n, pad, acc, name, repairs):
    if n == 0:
        return [pad] if lst else []
    if len(lst) == 0:
        repairs.append(f"{name}: empty -> padded x{n}")
        return [pad] * n
    if len(lst) == 1 and n > 1:
        return lst * n
    if len(lst) < n:
        repairs.append(f"{name}: len {len(lst)} < {n}, padded")
        return lst + [pad] * (n - len(lst))
    if len(lst) > n:
        repairs.append(f"{name}: len {len(lst)} > {n}, truncated")
        return lst[:n]
    return lst


def _normalize(sub, acc, field):
    """把代理某字段的子判定归一为标准记录。返回 (rec, repairs)。"""
    repairs = []
    value = [v for v in _as_list(sub.get("value")) if v not in (None, "")]
    if len(value) != len(_as_list(sub.get("value"))):
        repairs.append("value: dropped null/empty entries")
    n = len(value)
    confidence = _align(_as_list(sub.get("confidence")), n, "unknown", acc, "confidence", repairs)
    source = _align(_as_list(sub.get("source")), n, "llm_agent", acc, "source", repairs)
    method = _align(_as_list(sub.get("method")), n, "llm_agent", acc, "method", repairs)
    conf_fixed = [c if c in _CONF_DOMAIN else "unknown" for c in confidence]
    if sum(1 for a, b in zip(confidence, conf_fixed) if a != b):
        repairs.append("confidence: out-of-domain -> unknown")
    confidence = conf_fixed
    if n == 0 and not confidence:
        confidence = ["unknown"]
    out = {"project_accession": acc, "field": field, "value": value,
           "confidence": confidence, "source": source, "method": method,
           "note": sub.get("note", "")}
    if field == "host":
        tax = _align(_as_list(sub.get("tax_confidence")), n, "unknown", acc, "tax_confidence", repairs)
        tax_fixed = [t if t in _TAX_DOMAIN else "medium" for t in tax]
        if n == 0 and not tax:
            tax_fixed = ["unknown"]
        out["tax_confidence"] = tax_fixed
    for r in repairs:
        _replan_log(f"[normalize] {acc}/{field}: {r}")
    return out, repairs


def phase_merge(args):
    out = args.out_dir
    agent_path = os.path.join(out, "agent_llm_parallel.jsonl")
    if not os.path.exists(agent_path):
        print(f"[merge] 警告: 未找到 {agent_path}（代理尚未写入判定）")
        return
    merged = {f: load_jsonl_by_acc(os.path.join(out, f"ena_llm_infer_{f}.jsonl")) for f in FIELDS}
    verdicts = load_jsonl_by_acc(os.path.join(out, "agent_paper_verdicts.jsonl"))
    n_new = Counter()
    n_over = Counter()
    n_rep = Counter()
    n_demote = 0
    with open(agent_path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            acc = d.get("project_accession")
            if not acc:
                continue
            # 论文主题裁决（aligned=false -> 待降级 high→candidate，由 apply-demote 落盘）
            pv = d.get("papers")
            if isinstance(pv, list):
                vv = [v for v in pv if isinstance(v, dict) and v.get("pid")]
                verdicts[acc] = {"project_accession": acc, "verdicts": vv}
                n_demote += sum(1 for v in vv if v.get("aligned") is False)
            for f in FIELDS:
                sub = d.get(f)
                if not isinstance(sub, dict):
                    continue
                rec, repairs = _normalize(sub, acc, f)
                if repairs:
                    n_rep[f] += 1
                if acc in merged[f]:
                    n_over[f] += 1
                else:
                    n_new[f] += 1
                merged[f][acc] = rec
    with open(os.path.join(out, "agent_paper_verdicts.jsonl"), "w", encoding="utf-8") as vp:
        for d in verdicts.values():
            vp.write(json.dumps(d, ensure_ascii=False) + "\n")
    for f in FIELDS:
        path = os.path.join(out, f"ena_llm_infer_{f}.jsonl")
        with open(path, "w", encoding="utf-8") as fp:
            for d in merged[f].values():
                fp.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _rep(d):
        conf = d.get("confidence")
        if isinstance(conf, str):
            return conf
        if not conf:
            return "unknown"
        return min(conf, key=lambda x: _TIER.get(x, 0))

    stats = {}
    print("[merge] 分写三字段结果")
    for f in FIELDS:
        c = Counter(_rep(d) for d in merged[f].values())
        stats[f] = {"total": len(merged[f]), "by_confidence": dict(c),
                    "new": n_new[f], "overridden": n_over[f], "repaired": n_rep[f]}
        print(f"  {f:8}: total={len(merged[f]):4} new={n_new[f]:4} over={n_over[f]:4} "
              f"repaired={n_rep[f]:3} conf={dict(c)}")
    print(f"  论文主题裁决: {len(verdicts)} 项目，待降级(aligned=false) {n_demote} 篇 "
          f"-> agent_paper_verdicts.jsonl（再跑 --phase apply-demote 落盘）")
    with open(os.path.join(out, "llm_infer_stats.json"), "w", encoding="utf-8") as fp:
        json.dump(stats, fp, indent=2, ensure_ascii=False)


# ---- 阶段：apply-demote（把 LLM 判为不符主题的论文 high→candidate） --------

def phase_apply_demote(args):
    """读 agent_paper_verdicts.jsonl，把 aligned=false 的论文在 literature 里 high→candidate。
    幂等：首次把当前 literature 备份到 _bak/project_literature.pre_demote.jsonl，
    之后每次从备份重算 + 应用当前全部裁决。downstream（§3.1 只读 high）自动不消费被降级论文。"""
    out = args.out_dir
    lit_path = args.literature
    bak = os.path.join(out, "_bak", "project_literature.pre_demote.jsonl")
    if not os.path.exists(bak):
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        shutil.copyfile(lit_path, bak)
        _replan_log(f"[apply-demote] 备份原始 literature -> {bak}")
    verdicts = load_jsonl_by_acc(os.path.join(out, "agent_paper_verdicts.jsonl"))
    dem = {}
    for acc, rec in verdicts.items():
        s = {str(v.get("pid")) for v in rec.get("verdicts", [])
             if v.get("aligned") is False and v.get("pid")}
        if s:
            dem[acc] = s
    n_demoted = 0
    affected = set()
    out_lines = []
    with open(bak, encoding="utf-8") as f:  # 从备份重算，幂等
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            drop = dem.get(r.get("project_accession"), set())
            if drop:
                for p in r.get("papers", []):
                    if p.get("papersource") == "high" and _paper_pid(p) in drop:
                        p["papersource"] = "candidate"
                        p["demoted_by"] = "llm_topic"
                        n_demoted += 1
                        affected.add(r.get("project_accession"))
            out_lines.append(r)
    with open(lit_path, "w", encoding="utf-8") as f:
        for r in out_lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[apply-demote] 降级 {n_demoted} 篇 high→candidate（涉 {len(affected)} 项目）")
    print(f"  备份: {bak}")
    print(f"  输出: {lit_path}")
    print(f"  提示: 若需 §3.1 反映降级后的 high 集合，请重跑 ena_infer_31.py")


# ---- 阶段：reconcile（规则 × LLM） ---------------------------------------

def _base_val(v):
    """规则匹配只看冒号前（用户定 2026-08-13）：规则值可带 ':折射前原值' 后缀
    （如 'Japan:Tokyo'、'pig gut metagenome:Sus scrofa'），比较时剥掉。"""
    return str(v).split(":", 1)[0].strip().lower()


def _norm_vals(rec):
    """归一取值集合（小写、去 ':detail' 后缀、去空、剔 unknown）。"""
    if not rec:
        return set()
    vals = rec.get("value") or []
    if isinstance(vals, str):
        vals = [vals]
    return {_base_val(v) for v in vals if v not in (None, "", "unknown")}


def _dates_compatible(a, b):
    """date 粒度通配比较（用户定 2026-08-13）：'XX' 为通配段，
    '2019-XX-XX' 兼容 '2019'/'2019-03-15'；'2019-03-XX' 兼容 '2019-03-15' 不兼容 '2019-04-01'。"""
    pa, pb = a.split("-"), b.split("-")
    for i in range(min(len(pa), len(pb))):
        xa, xb = pa[i], pb[i]
        if xa == "xx" or xb == "xx":
            continue
        if xa != xb:
            return False
    return True


def _rep_conf(rec):
    conf = rec.get("confidence") if rec else None
    if isinstance(conf, str):
        return conf
    if not conf:
        return "unknown"
    return max(conf, key=lambda x: _TIER.get(x, 0))


def reconcile_field(field, rule_recs, llm_recs):
    final = {}
    review = {}
    stats = Counter()
    for acc in sorted(set(rule_recs) | set(llm_recs)):
        r = rule_recs.get(acc)
        l = llm_recs.get(acc)
        rv, lv = _norm_vals(r), _norm_vals(l)
        if not rv and not lv:
            stats["both_unknown"] += 1
            continue  # 双方都无值 -> 不写 final（仍 unknown）
        if rv and not lv:
            final[acc] = r
            stats["rule_only"] += 1
            continue
        if lv and not rv:
            final[acc] = l
            stats["llm_only"] += 1
            continue
        # 双方都有值
        if field == "date":
            # date：XX 通配段兼容即 agree（如 2019-XX-XX ~ 2019-03-15）
            _agree = any(_dates_compatible(a, b) for a in rv for b in lv)
        else:
            _agree = bool(rv & lv)  # 取值集合相交 -> agree
        if _agree:
            vals = list(dict.fromkeys((r.get("value") or []) + (l.get("value") or [])))
            n = len(vals)
            final[acc] = {"project_accession": acc, "field": field, "value": vals,
                          "confidence": ["high"] * n, "source": ["rule+llm"] * n,
                          "method": ["agree"] * n, "note": "rule & llm agree"}
            stats["agree"] += 1
            continue
        # disagree
        rt, lt = _TIER.get(_rep_conf(r), 0), _TIER.get(_rep_conf(l), 0)
        if rt == lt:
            # 置信相当 -> flag review（暂定），暂取规则值（字典有据）
            rec = dict(r)
            rec["needs_review"] = True
            rec["review_note"] = f"disagree equal-conf: rule={sorted(rv)} vs llm={sorted(lv)}"
            rec["method"] = ["disagree_review"]
            final[acc] = rec
            review[acc] = {"project_accession": acc, "field": field,
                           "rule": r, "llm": l}
            stats["disagree_review"] += 1
        else:
            winner, wname = (r, "rule") if rt > lt else (l, "llm")
            rec = dict(winner)
            rec["method"] = [f"disagree_{wname}"]
            rec["note"] = f"disagree, took {wname} (higher conf): rule={sorted(rv)} vs llm={sorted(lv)}"
            final[acc] = rec
            stats[f"disagree_{wname}"] += 1
    return final, review, stats


def phase_reconcile(args):
    out = args.out_dir
    all_stats = {}
    print("[reconcile] 规则 × LLM 合并")
    for f in FIELDS:
        rule = load_jsonl_by_acc(os.path.join(out, f"{f}_infer.jsonl"))
        llm = load_jsonl_by_acc(os.path.join(out, f"ena_llm_infer_{f}.jsonl"))
        final, review, stats = reconcile_field(f, rule, llm)
        with open(os.path.join(out, f"reconciled_{f}.jsonl"), "w", encoding="utf-8") as fp:
            for d in final.values():
                fp.write(json.dumps(d, ensure_ascii=False) + "\n")
        with open(os.path.join(out, f"review_{f}.jsonl"), "w", encoding="utf-8") as fp:
            for d in review.values():
                fp.write(json.dumps(d, ensure_ascii=False) + "\n")
        all_stats[f] = dict(stats)
        print(f"  {f:8}: reconciled={len(final):4} review={len(review):3} | {dict(stats)}")
    with open(os.path.join(out, "reconcile_stats.json"), "w", encoding="utf-8") as fp:
        json.dump(all_stats, fp, indent=2, ensure_ascii=False)
    print(f"  统计 -> {os.path.join(out, 'reconcile_stats.json')}")


# ---- CLI -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="§3.2-parallel：LLM 与规则平行，一次读 evidence 同判 country/date/host")
    ap.add_argument("--phase", required=True,
                    choices=["batch", "merge", "reconcile", "apply-demote"])
    ap.add_argument("--scope", default="high-paper",
                    choices=["high-paper", "no-high-paper", "all", "union"],
                    help="batch 选项目范围：high-paper(默认,有≥1篇high论文) / "
                         "no-high-paper(可选补充档,无high论文、仅study_meta) / all / union")
    ap.add_argument("--study-meta", default=os.path.join(DEF_OUT, "project_study_meta.json"))
    ap.add_argument("--literature", default=os.path.join(DEF_OUT, "project_literature.jsonl"))
    ap.add_argument("--infer-country", default=os.path.join(DEF_OUT, "country_infer.jsonl"))
    ap.add_argument("--infer-date", default=os.path.join(DEF_OUT, "date_infer.jsonl"))
    ap.add_argument("--infer-host", default=os.path.join(DEF_OUT, "host_infer.jsonl"))
    ap.add_argument("--out-dir", default=DEF_OUT)
    args = ap.parse_args()
    _replan_log("ena_agent_parallel --phase %s --scope %s --out-dir %s"
                % (args.phase, getattr(args, "scope", ""), args.out_dir))

    if args.phase == "batch":
        phase_batch(args)
    elif args.phase == "merge":
        phase_merge(args)
    elif args.phase == "reconcile":
        phase_reconcile(args)
    elif args.phase == "apply-demote":
        phase_apply_demote(args)


if __name__ == "__main__":
    main()
