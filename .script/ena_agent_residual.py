#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.2 LLM 残差的可复用脚本：打印 evidence + 写入结果。

设计（对齐 Replan.md §3.2，不走外部 API）：
  - 本脚本不判值，只负责 I/O 与去重。
  - "你"（WorkBuddy 代理，本身就是 LLM）读 evidence → 逐条判 → 写判定文件。
  - 会话内不报告任何结果，只落盘（防上下文膨胀）。

阶段：
  batch   抽取 §3.1 残差（content_reliability != high 或 value=unknown/null），
          组装 evidence_text，写入 agent_residual_<field>.jsonl；
          对话里只打印摘要（数量 / 文件路径 / 已完成跳过数），不打印 evidence。
          支持断点续跑：已完成集合（ena_llm_infer_<field>.jsonl + agent_llm_<field>.jsonl
          中的 project_accession）自动跳过。

  merge   读取代理写好的 agent_llm_<field>.jsonl（每条判定），
          与已有 ena_llm_infer_<field>.jsonl 合并（代理判定覆盖旧值，按 project_accession 去重），
          写入 ena_llm_infer_<field>.jsonl + llm_infer_stats.json；对话里只打印统计摘要。

约定：
  - 代理判定文件 agent_llm_<field>.jsonl 每行一条：
      {"project_accession","field","value","confidence","content_reliability","source","method":"llm_agent","note"}
    value: 国名(str)/国名列表(list)/NotCountry(str)/年(str)/宿主(str)/null(无法判断)
    confidence: high|medium|low|unknown|NotCountry
  - 本脚本只读输入、不改任何源文件；所有产物落在 --out-dir（默认 .tmp）。
"""
import os
import json
import argparse
from collections import Counter
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

# ---- 输入加载 -------------------------------------------------------------

def load_infer(path):
    """§3.1 字段推断结果：acc -> rec（仅该 field 的记录）。"""
    recs = {}
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            recs[d["project_accession"]] = d
    return recs

def load_study_meta(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_literature(path):
    """acc -> rec（含 papers[]）。"""
    recs = {}
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            recs[d["project_accession"]] = d
    return recs

# ---- 残差判定 -------------------------------------------------------------

def is_residual(rec):
    """§3.2 路由：content_reliability 不足（!=high）或 value 未知 → 残差。"""
    if rec is None:
        return True
    if rec.get("value") in (None, "unknown", []):
        return True
    if rec.get("content_reliability") != "high":
        return True
    return False

# ---- evidence 组装 --------------------------------------------------------

def build_evidence(acc, study_meta, lit_rec, infer_rec, cap_desc=2000, cap_abs=1200):
    """把供 LLM 直读的文本拼成一个 evidence_text。"""
    parts = []
    study = study_meta.get(acc, {})
    title = (study.get("study_title") or "").strip()
    center = (study.get("center_name") or "").strip()
    desc = (study.get("study_description") or "").strip()
    if title:
        parts.append(f"[study_title] {title}")
    if center:
        parts.append(f"[center_name] {center}")
    if desc:
        parts.append(f"[study_description] {desc[:cap_desc]}")
    # literature：仅 papersource=high 才可信（§2.2 / §3.0 标签 B）
    if lit_rec:
        for p in lit_rec.get("papers", []):
            if p.get("papersource") != "high":
                continue
            t = (p.get("title") or "").strip()
            ab = (p.get("abstract") or "").strip()
            if t:
                parts.append(f"[lit_title] {t[:300]}")
            if ab:
                parts.append(f"[lit_abstract] {ab[:cap_abs]}")
    # §3.1 基线（供 LLM 参考：规则找到了什么、为什么没升 high）
    if infer_rec and infer_rec.get("method") not in (None, "none"):
        rp = (f"method={infer_rec.get('method')} | value={infer_rec.get('value')} "
              f"| content_reliability={infer_rec.get('content_reliability')} "
              f"| matched={infer_rec.get('matched_tokens')}")
        parts.append(f"[rule_partial] {rp}")
    return "\n".join(parts)

# ---- 阶段：batch ----------------------------------------------------------

def phase_batch(args):
    out = args.out_dir
    field = args.field
    infer_path = args.infer or os.path.join(out, f"{field}_infer.jsonl")
    study_meta = load_study_meta(args.study_meta)
    lit = load_literature(args.literature)
    infer = load_infer(infer_path)

    # 已完成集合（断点续跑）
    done = set()
    llm_path = os.path.join(out, f"ena_llm_infer_{field}.jsonl")
    agent_path = os.path.join(out, f"agent_llm_{field}.jsonl")
    for p in (llm_path, agent_path):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    done.add(json.loads(line)["project_accession"])

    # 项目全集：study_meta ∪ infer
    all_accs = set(study_meta.keys()) | set(infer.keys())

    residual = []
    skipped_none = 0
    for acc in sorted(all_accs):
        if acc in done:
            skipped_none += 1
            continue
        rec = infer.get(acc)
        if not is_residual(rec):
            continue
        ev = build_evidence(acc, study_meta, lit.get(acc), rec)
        residual.append({
            "project_accession": acc,
            "field": field,
            "rule_partial": {
                "value": (rec or {}).get("value"),
                "confidence": (rec or {}).get("confidence"),
                "content_reliability": (rec or {}).get("content_reliability"),
                "source": (rec or {}).get("source"),
                "method": (rec or {}).get("method"),
                "matched_tokens": (rec or {}).get("matched_tokens"),
            },
            "evidence_text": ev,
        })

    out_path = os.path.join(out, f"agent_residual_{field}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for d in residual:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    # 对话里只打印摘要（不打印 evidence，防上下文膨胀）
    print(f"[batch] field={field}")
    print(f"  项目全集         : {len(all_accs)}")
    print(f"  已完成(跳过)     : {skipped_none}")
    print(f"  残差待判         : {len(residual)}  ->  {out_path}")
    print(f"  读取输入: study_meta={args.study_meta} | literature={args.literature} | infer={infer_path}")
    print(f"  下一步: 代理读 {os.path.basename(out_path)} 逐条判，写 agent_llm_{field}.jsonl，再跑 --phase merge")
    return out_path

# ---- 阶段：merge ----------------------------------------------------------

def _normalize(rec, field):
    """校验/补全代理判定记录，强制 method=llm_agent。"""
    out = {
        "project_accession": rec["project_accession"],
        "field": rec.get("field", field),
        "value": rec.get("value"),
        "confidence": rec.get("confidence"),
        "content_reliability": rec.get("content_reliability"),
        "source": rec.get("source", "study_meta"),
        "method": "llm_agent",
        "note": rec.get("note", ""),
    }
    # content_reliability 缺省由 confidence 推导
    if out["content_reliability"] in (None, ""):
        c = out["confidence"]
        out["content_reliability"] = {"high": "high", "medium": "medium",
                                      "low": "low", "NotCountry": "high"}.get(c, None)
    return out

def phase_merge(args):
    out = args.out_dir
    field = args.field
    llm_path = os.path.join(out, f"ena_llm_infer_{field}.jsonl")
    agent_path = os.path.join(out, f"agent_llm_{field}.jsonl")

    merged = {}
    if os.path.exists(llm_path):
        with open(llm_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                merged[d["project_accession"]] = d

    n_new = 0
    n_over = 0
    if os.path.exists(agent_path):
        with open(agent_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                rec = _normalize(raw, field)
                if rec["project_accession"] in merged:
                    n_over += 1
                else:
                    n_new += 1
                merged[rec["project_accession"]] = rec
    else:
        print(f"[merge] 警告: 未找到 {agent_path}（代理尚未写入判定）")
        return

    # 写回
    with open(llm_path, "w", encoding="utf-8") as f:
        for d in merged.values():
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    c = Counter(d["confidence"] for d in merged.values())
    stats = {
        "field": field,
        "total": len(merged),
        "by_confidence": dict(c),
        "new_this_merge": n_new,
        "overridden": n_over,
    }
    with open(os.path.join(out, "llm_infer_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"[merge] field={field}")
    print(f"  并入新判定       : {n_new}")
    print(f"  覆盖旧值         : {n_over}")
    print(f"  累计总计         : {len(merged)}  ->  {llm_path}")
    print(f"  置信度分布       : {dict(c)}")
    print(f"  统计             : {os.path.join(out, 'llm_infer_stats.json')}")

# ---- CLI -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="§3.2 LLM 残差：batch 抽残差+打印evidence / merge 写入结果")
    ap.add_argument("--phase", required=True, choices=["batch", "merge"])
    ap.add_argument("--field", required=True, choices=["country", "date", "host"])
    ap.add_argument("--study-meta", default=os.path.join(DEF_OUT, "project_study_meta.json"))
    ap.add_argument("--literature", default=os.path.join(DEF_OUT, "project_literature.jsonl"))
    ap.add_argument("--infer", default=None,
                    help="§3.1 字段推断 jsonl；缺省 <out-dir>/<field>_infer.jsonl")
    ap.add_argument("--out-dir", default=DEF_OUT)
    args = ap.parse_args()
    _replan_log("ena_agent_residual --phase %s --field %s --out-dir %s"
                % (args.phase, args.field, args.out_dir))

    if args.phase == "batch":
        phase_batch(args)
    elif args.phase == "merge":
        phase_merge(args)

if __name__ == "__main__":
    main()
