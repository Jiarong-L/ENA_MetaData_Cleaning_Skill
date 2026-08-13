#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.4 final_merge：合并 §3.1(rule) / §3.2(llm_agent) / §3.3(manual) 三源，
输出 per-field final 裁定（见 Replan.md §3.4）。

取值政策（用户定）：
  1. **manual 优先**（用户背书，最高档）。
  2. 无 manual → **优先取 LLM 值**（LLM 总体更精确）；一致性标签仅作状态标注：
     - LLM 值集合 ⊆ 规则值列表（字面；规则值先剥 `:折射前` 后缀，date 用 XX 通配）
       → `consistent`（consistency_via=literal）；
     - 否则轻量归一（host 去 `metagenome`/部位词、小写）后再判包含
       → `consistent`（consistency_via=light）；
     - 否则 → `conflict`（多数为命名/规范差异，如 `Sus scrofa gut metagenome`
       不在 `[pig, human, pig metagenome, Sus scrofa]` 但同义）——**仍取 LLM 值**，
       并写入裁决队列 `final_conflict_<field>.jsonl` 送 LLM 判语义等价。
  3. 仅规则有值 → 取规则值（consistency=rule_only）；仅 LLM 有值 → consistency=llm_only。
  4. 三源均无值 → 不写 final（仍 unknown）。

阶段：
  merge（默认）    三源合并 → final_<field>.jsonl + final_<field>_stats.json
                   + final_conflict_<field>.jsonl（conflict 裁决队列，供 LLM 读）。
  apply-verdicts   读 LLM 裁决 `final_verdicts_<field>.jsonl`
                   （每行 {"project_accession","field","equivalent":true|false,"note"}），
                   把 equivalent=true 的 conflict 改标 consistent
                   （consistency_via=llm_adjudicated），重写 final_<field>.jsonl
                   （首次备份 final_<field>.pre_verdicts.jsonl，幂等）。

输入（默认同 --out-dir，即 .tmp）：
  - <field>_infer.jsonl        §3.1 rule 基线（method=rule_*；值可带 `:折射前` 后缀）
  - ena_llm_infer_<field>.jsonl §3.2 LLM 判定（平行架构 merge 产出）
  - ena_manual_<field>.jsonl   §3.3 manual store（由 ena_load_manual 生成）

设计：只读三源、确定性、可重跑（覆盖写）；不改动任何源文件。
"""
import os, re, json, argparse, collections
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


# ---- 值比较（规则匹配只看冒号前；date XX 通配；host 轻量归一预过滤） --------

def _base_val(v):
    """剥 ':折射前' 后缀并小写（如 'Japan:Tokyo'->'japan'、
    'pig gut metagenome:Sus scrofa'->'pig gut metagenome'）。"""
    return str(v).split(":", 1)[0].strip().lower()


def _dates_compatible(a, b):
    """date XX 通配段比较：'2019-XX-XX' 兼容 '2019-03-15'；
    '2019-03-XX' 兼容 '2019-03-15' 不兼容 '2019-04-01'。"""
    pa, pb = a.split("-"), b.split("-")
    for i in range(min(len(pa), len(pb))):
        xa, xb = pa[i], pb[i]
        if xa == "xx" or xb == "xx":
            continue
        if xa != xb:
            return False
    return True


_HOST_SITE_WORDS = {
    "gut", "oral", "skin", "vaginal", "blood", "feces", "faeces", "stool",
    "urine", "saliva", "nasal", "ear", "eye", "wound", "tongue", "plaque",
    "milk", "manure", "rumen", "digestive", "lung", "nasopharyngeal", "skeleton",
}

def _light_norm(field, v):
    """轻量归一预过滤：host 去 ' metagenome' 尾与部位词（'sus scrofa gut metagenome'
    -> 'sus scrofa'）；country 即 _base_val。用于把明显规范匹配先滤掉。"""
    s = _base_val(v)
    if field == "host":
        s = re.sub(r"\s*metagenome$", "", s)
        s = " ".join(t for t in s.split() if t not in _HOST_SITE_WORDS)
    return s.strip()


def _values(rec):
    vals = rec.get("value") if rec else None
    if isinstance(vals, str):
        vals = [vals]
    return [str(v).strip() for v in (vals or [])
            if str(v).strip().lower() not in ("", "unknown", "na", "none")]


def gate_consistency(field, llm_vals, rule_vals):
    """一致性闸门。返回 (label, via)：label ∈ consistent/conflict；via ∈ literal/light/None。"""
    if field == "date":
        ok = all(any(_dates_compatible(_base_val(a), _base_val(b)) for b in rule_vals)
                 for a in llm_vals)
        return ("consistent", "literal") if ok else ("conflict", None)
    rb = {_base_val(v) for v in rule_vals}
    if {_base_val(v) for v in llm_vals} <= rb:
        return "consistent", "literal"
    rl = {_light_norm(field, v) for v in rule_vals}
    if {_light_norm(field, v) for v in llm_vals} <= rl:
        return "consistent", "light"
    return "conflict", None


# ---- I/O -----------------------------------------------------------------

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


def _note_of(rec):
    note = rec.get("note")
    if note:
        return note
    ev = rec.get("evidence")
    if isinstance(ev, str):
        return ev
    if isinstance(ev, list):
        return " ; ".join(f"[{e.get('value')}|{e.get('sub_source')}] {e.get('snippet')}" for e in ev)
    return ""


def _final_rec(acc, field, winner, decided_by, consistency, via, n_sources, extra_note=""):
    out = {
        "project_accession": acc,
        "field": field,
        "value": winner.get("value"),
        "confidence": winner.get("confidence"),
        "source": winner.get("source"),
        "method": winner.get("method"),
        "evidence_basis": winner.get("evidence_basis"),
        "note": (extra_note + " | " if extra_note else "") + _note_of(winner),
        "decided_by": decided_by,          # manual / llm_preferred / rule_only
        "consistency": consistency,        # manual / consistent / conflict / rule_only / llm_only
        "consistency_via": via,            # literal / light / llm_adjudicated / None
        "n_sources": n_sources,
    }
    if field == "host":
        out["tax_confidence"] = winner.get("tax_confidence")
    return out


# ---- 阶段：merge ----------------------------------------------------------

def merge_field(field, out_dir):
    rule = load_jsonl(os.path.join(out_dir, f"{field}_infer.jsonl"))
    llm = load_jsonl(os.path.join(out_dir, f"ena_llm_infer_{field}.jsonl"))
    manual = load_jsonl(os.path.join(out_dir, f"ena_manual_{field}.jsonl"))

    all_accs = set(rule) | set(llm) | set(manual)
    final, conflicts = [], []
    stats = {
        "field": field,
        "total_projects": len(all_accs),
        "decided_by": collections.Counter(),
        "consistency": collections.Counter(),
        "consistency_via": collections.Counter(),
        "no_value": 0,
    }

    for acc in sorted(all_accs):
        r, l, m = rule.get(acc), llm.get(acc), manual.get(acc)
        mv, lv, rv = _values(m), _values(l), _values(r)
        n_src = sum(1 for x in (mv, lv, rv) if x)
        if not n_src:
            stats["no_value"] += 1
            continue

        if mv:  # manual 最高档
            rec = _final_rec(acc, field, m, "manual", "manual", None, n_src)
        elif lv:  # 优先取 LLM
            if rv:
                label, via = gate_consistency(field, lv, rv)
                note = ""
                if label == "conflict":
                    note = (f"rule={sorted({_base_val(v) for v in rv})} "
                            f"vs llm={sorted({_base_val(v) for v in lv})}")
                    conflicts.append({
                        "project_accession": acc, "field": field,
                        "llm_value": lv, "rule_value": rv,
                        "llm": l, "rule": r,
                    })
                rec = _final_rec(acc, field, l, "llm_preferred", label, via, n_src, note)
            else:
                rec = _final_rec(acc, field, l, "llm_preferred", "llm_only", None, n_src)
        else:  # 仅规则有值
            rec = _final_rec(acc, field, r, "rule_only", "rule_only", None, n_src)

        final.append(rec)
        stats["decided_by"][rec["decided_by"]] += 1
        stats["consistency"][rec["consistency"]] += 1
        if rec["consistency_via"]:
            stats["consistency_via"][rec["consistency_via"]] += 1

    outp = os.path.join(out_dir, f"final_{field}.jsonl")
    with open(outp, "w", encoding="utf-8") as w:
        for d in final:
            w.write(json.dumps(d, ensure_ascii=False) + "\n")
    cpath = os.path.join(out_dir, f"final_conflict_{field}.jsonl")
    with open(cpath, "w", encoding="utf-8") as w:
        for d in conflicts:
            w.write(json.dumps(d, ensure_ascii=False) + "\n")
    for k in ("decided_by", "consistency", "consistency_via"):
        stats[k] = dict(stats[k])
    statsp = os.path.join(out_dir, f"final_{field}_stats.json")
    with open(statsp, "w", encoding="utf-8") as w:
        json.dump(stats, w, indent=2, ensure_ascii=False)

    print(f"[final_merge] field={field}")
    print(f"  项目全集       : {len(all_accs)}")
    print(f"  final 写出     : {len(final)}  ->  {outp}")
    print(f"  取值路径       : {stats['decided_by']}")
    print(f"  一致性         : {stats['consistency']}")
    print(f"  conflict 队列  : {len(conflicts)}  ->  {cpath}（送 LLM 裁决语义等价）")
    print(f"  统计           : {statsp}")


# ---- 阶段：apply-verdicts --------------------------------------------------

def apply_verdicts(field, out_dir):
    """读 LLM 语义等价裁决，把 equivalent=true 的 conflict 改标 consistent（幂等）。"""
    finalp = os.path.join(out_dir, f"final_{field}.jsonl")
    bak = os.path.join(out_dir, f"final_{field}.pre_verdicts.jsonl")
    vp = os.path.join(out_dir, f"final_verdicts_{field}.jsonl")
    verdicts = load_jsonl(vp)
    if not verdicts:
        print(f"[apply-verdicts] field={field}: 无 {vp}，跳过")
        return
    src = bak if os.path.exists(bak) else finalp  # 幂等：有备份则从备份重算
    if not os.path.exists(src):
        print(f"[apply-verdicts] field={field}: 缺 {finalp}，跳过")
        return
    if not os.path.exists(bak):
        with open(finalp, encoding="utf-8") as f, open(bak, "w", encoding="utf-8") as w:
            w.write(f.read())
    n_flip = n_keep = 0
    rows = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            v = verdicts.get(d["project_accession"])
            if d.get("consistency") == "conflict" and v:
                if v.get("equivalent") is True:
                    d["consistency"] = "consistent"
                    d["consistency_via"] = "llm_adjudicated"
                    d["note"] = (d.get("note") or "") + f" | llm_adjudicated: {v.get('note', '')}"
                    n_flip += 1
                else:
                    n_keep += 1
            rows.append(d)
    with open(finalp, "w", encoding="utf-8") as w:
        for d in rows:
            w.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"[apply-verdicts] field={field}: conflict→consistent {n_flip}，维持 conflict {n_keep}，"
          f"重写 {finalp}（备份 {bak}）")


def main():
    ap = argparse.ArgumentParser(
        description="§3.4 final_merge：manual 优先；无 manual 取 LLM 值 + consistent/conflict 闸门")
    ap.add_argument("--phase", default="merge", choices=["merge", "apply-verdicts"])
    ap.add_argument("--field", required=True, choices=["country", "date", "host", "all"])
    ap.add_argument("--out-dir", default=DEF_OUT)
    args = ap.parse_args()
    _replan_log("ena_final_merge --phase %s --field %s --out-dir %s"
                % (args.phase, args.field, args.out_dir))
    fields = ["country", "date", "host"] if args.field == "all" else [args.field]
    for field in fields:
        if args.phase == "merge":
            merge_field(field, args.out_dir)
        else:
            apply_verdicts(field, args.out_dir)


if __name__ == "__main__":
    main()
