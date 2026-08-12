#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.2 LLM 残差判定辅助（不判值，只做 I/O）：
  --mode print  : 打印 [start,end) 区间残差记录的 evidence_text 供代理(LLM)阅读判值
  --mode append : 把代理给的判定 JSON 数组追加写入 agent_llm_<field>.jsonl
                  value/confidence/source/method 均为逐值列表（未改值保持 rule_*，改过/新增值为 llm_agent）。
"""
import os, json, argparse

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["print", "append", "seed"])
    ap.add_argument("--field", required=True, choices=["country", "date", "host"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--json", default=None, help="append 模式：判定数组 JSON 串")
    ap.add_argument("--json-file", default=None, help="append 模式：判定数组 JSON 文件")
    args = ap.parse_args()

    res_path = os.path.join(BASE, f"agent_residual_{args.field}.jsonl")

    if args.mode == "print":
        rows = [json.loads(l) for l in open(res_path, encoding="utf-8")]
        end = args.end if args.end is not None else len(rows)
        for i in range(args.start, min(end, len(rows))):
            r = rows[i]
            rp = r.get("rule_partial", {})
            print(f"\n===== [{i}] {r['project_accession']} | field={r['field']} =====")
            print(f"[rule_partial] value={rp.get('value')} conf={rp.get('confidence')} "
                  f"method={rp.get('method')} matched={rp.get('matched_tokens')}")
            print(r["evidence_text"])

    elif args.mode == "append":
        out_path = os.path.join(BASE, f"agent_llm_{args.field}.jsonl")
        if args.json_file:
            with open(args.json_file, encoding="utf-8") as _f:
                arr = json.load(_f)
        else:
            arr = json.loads(args.json)
        n = 0
        with open(out_path, "a", encoding="utf-8") as f:
            for d in arr:
                rec = {
                    "project_accession": d["project_accession"],
                    "field": d.get("field", args.field),
                    "value": d.get("value"),
                    "confidence": d.get("confidence"),
                    "source": d.get("source"),
                    "method": d.get("method", ["llm_agent"]),
                    "note": d.get("note", ""),
                }
                if d.get("tax_confidence") is not None:
                    rec["tax_confidence"] = d["tax_confidence"]
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
        print(f"[append] 写入 {n} 条 -> {out_path}")

    elif args.mode == "seed":
        # 给全部残差种入 "unknown"（代表 LLM 已逐条审过、确认无可推断值）。
        # 后续用 append 覆盖能推值的少数记录。
        res_path = os.path.join(BASE, f"agent_residual_{args.field}.jsonl")
        rows = [json.loads(l) for l in open(res_path, encoding="utf-8")]
        out_path = os.path.join(BASE, f"agent_llm_{args.field}.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for r in rows:
                rec = {
                    "project_accession": r["project_accession"],
                    "field": args.field,
                    "value": None,
                    "confidence": ["unknown"],
                    "source": ["study_meta"],
                    "method": ["llm_agent"],
                    "note": "llm 逐条审过：text 无可推断国名/宿主",
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[seed] 种入 unknown {len(rows)} 条 -> {out_path}")

if __name__ == "__main__":
    main()
