#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.4 final_merge：按双轴优先级合并 §3.1(rule) / §3.2(llm_agent) / §3.3(manual) 三源，
输出 per-field final 裁定。

双轴优先级（见 Replan.md §3.4；对齐用户原话「优先级A：high>medium>low；优先级B：用户>LLM>规则」）：
  轴 A（主导·置信度，高→低）：high / NotCountry > medium > low > unknown
  轴 B（同置信度内决胜·来源）：manual > llm_agent > rule_*

合并步骤（逐项目·逐字段）：
  1. 收集该项目该字段全部候选（来自三个源）。
  2. 按 (轴A tier, 轴B rank) 升序取最小 = 胜者。
  3. 胜者写入 final；若胜者置信度为 unknown（无任何信号）→ value 置 null。

输入（默认同 --out-dir，即 .tmp）：
  - <field>_infer.jsonl      §3.1 rule 基线（method=rule_*；未命中 method="none"）
  - agent_llm_<field>.jsonl  §3.2 LLM 判定（method=llm_agent）
  - ena_manual_<field>.jsonl §3.3 manual store（method=manual，由 ena_load_manual 生成）

输出：
  - final_<field>.jsonl        每行一项目·字段最终裁定（含 n_candidates / won_by 审计字段）
  - final_<field>_stats.json   计数汇总

设计：
  - 只读三源、原子写新文件；不改变任何源文件。
  - 确定性、可重跑（覆盖写，无断点续跑需求）。
  - 不读 ena_llm_infer_<field>.jsonl（那是 §3.2 内部 merge 视图，与 rule+llm 源重复）。
"""
import os, json, argparse, collections
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPLAN_ROOT = os.path.dirname(SCRIPT_DIR)  # .replan
DEF_OUT = os.path.join(REPLAN_ROOT, ".tmp")
LOG_DIR = os.path.join(REPLAN_ROOT, ".log")

def _replan_log(msg):
    """追加一行运行日志到 .log/run_YYYY-MM-DD.log（失败静默，不影响主流程）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        lp = os.path.join(LOG_DIR, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        with open(lp, "a", encoding="utf-8") as _f:
            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass

# 轴 A：置信度档（数字越小越优先）
CONF_TIER = {"high": 0, "NotCountry": 0, "medium": 1, "low": 2, "unknown": 3}
# 轴 B：来源档（数字越小越优先）；manual > llm_agent > rule_*
def src_rank(method):
    if method == "manual":
        return 0
    if method == "llm_agent":
        return 1
    if isinstance(method, str) and method.startswith("rule_"):
        return 2
    return 2  # 未知方法按规则档兜底

def conf_tier(c):
    return CONF_TIER.get(c, 3)  # 未知置信度按 unknown 兜底

def _rep_conf(rec):
    """从 confidence 列表中取最高值用于排序（兼容旧单值 str）。"""
    conf_list = rec.get("confidence", [])
    if isinstance(conf_list, str):
        return conf_list
    if not conf_list:
        return "unknown"
    return min(conf_list, key=lambda c: CONF_TIER.get(c, 3))

def _rep_method(rec):
    """从 method 列表中取最高 rank 用于排序（兼容旧单值 str）。"""
    method_list = rec.get("method", [])
    if isinstance(method_list, str):
        return method_list
    if not method_list:
        return "unknown"
    return min(method_list, key=lambda m: src_rank(m))

def load_jsonl(path):
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

def merge_field(field, out_dir):
    rule = load_jsonl(os.path.join(out_dir, f"{field}_infer.jsonl"))
    llm = load_jsonl(os.path.join(out_dir, f"agent_llm_{field}.jsonl"))
    manual = load_jsonl(os.path.join(out_dir, f"ena_manual_{field}.jsonl"))

    all_accs = set(rule) | set(llm) | set(manual)

    final = []
    stats = {
        "field": field,
        "total_projects": len(all_accs),
        "by_confidence": collections.Counter(),
        "by_method": collections.Counter(),
        "resolved_by": {"sole": 0, "axis_A": 0, "axis_B": 0},
        "truly_unknown": 0,
    }

    for acc in sorted(all_accs):
        cands = [r for r in (rule.get(acc), llm.get(acc), manual.get(acc)) if r]
        if not cands:
            continue

        def key(r):
            return (conf_tier(_rep_conf(r)), src_rank(_rep_method(r)))

        ranked = sorted(cands, key=key)
        winner = ranked[0]
        best_a = key(winner)[0]
        same_a = [r for r in ranked if key(r)[0] == best_a]
        if len(cands) == 1:
            how = "sole"
        elif len(same_a) == 1:
            how = "axis_A"
        else:
            how = "axis_B"
        stats["resolved_by"][how] += 1

        rep_c = _rep_conf(winner)
        val = winner.get("value")
        if conf_tier(rep_c) == 3:  # unknown tier
            val = None
            conf = ["unknown"]
        else:
            conf = winner.get("confidence", [])

        # note：优先 note 字段，否则从 evidence 列表拼接
        note = winner.get("note")
        if not note:
            ev = winner.get("evidence")
            if isinstance(ev, str):
                note = ev
            elif isinstance(ev, list):
                note = " ; ".join(f"[{e.get('value')}|{e.get('sub_source')}] {e.get('snippet')}" for e in ev)
            else:
                note = ""

        out = {
            "project_accession": acc,
            "field": field,
            "value": val,
            "confidence": conf,
            "source": winner.get("source"),
            "method": winner.get("method"),
            "evidence_basis": winner.get("evidence_basis"),
            "note": note,
            "n_candidates": len(cands),
            "won_by": how,
        }
        if field == "host":
            out["tax_confidence"] = winner.get("tax_confidence")
        final.append(out)
        stats["by_confidence"][rep_c] += 1
        stats["by_method"][_rep_method(winner)] += 1
        if rep_c == "unknown":
            stats["truly_unknown"] += 1

    outp = os.path.join(out_dir, f"final_{field}.jsonl")
    with open(outp, "w", encoding="utf-8") as w:
        for d in final:
            w.write(json.dumps(d, ensure_ascii=False) + "\n")
    stats["by_confidence"] = dict(stats["by_confidence"])
    stats["by_method"] = dict(stats["by_method"])
    statsp = os.path.join(out_dir, f"final_{field}_stats.json")
    with open(statsp, "w", encoding="utf-8") as w:
        json.dump(stats, w, indent=2, ensure_ascii=False)

    print(f"[final_merge] field={field}")
    print(f"  项目全集       : {len(all_accs)}")
    print(f"  final 写出     : {len(final)}  ->  {outp}")
    print(f"  置信度分布     : {stats['by_confidence']}")
    print(f"  胜者来源分布   : {stats['by_method']}")
    print(f"  裁决方式       : {stats['resolved_by']}")
    print(f"  真正 unknown   : {stats['truly_unknown']}")
    print(f"  统计           : {statsp}")

def main():
    ap = argparse.ArgumentParser(description="§3.4 final_merge：三源双轴优先级合并")
    ap.add_argument("--field", required=True, choices=["country", "date", "host", "all"])
    ap.add_argument("--out-dir", default=DEF_OUT)
    args = ap.parse_args()
    _replan_log("ena_final_merge --field %s --out-dir %s" % (args.field, args.out_dir))
    fields = ["country", "date", "host"] if args.field == "all" else [args.field]
    for field in fields:
        merge_field(field, args.out_dir)

if __name__ == "__main__":
    main()
