#!/usr/bin/env python3
"""Load the reusable §3.3 manual-check resources (manual_check_<field>.json) into
the per-field manual store (ena_manual_<field>.jsonl) consumed by §3.4 final_merge.

Design:
- manual_check_<field>.json are the CANONICAL, cross-project, machine-loadable
  resources (one per inference field: country / date / host). Currently only
  manual_check_country.json exists; date / host will each be generated separately
  later.
- They are NOT hand-edited by humans; the LLM extracts manual judgments from the
  conversation (user provides prose -> LLM normalizes -> appends a JSON object to
  the relevant manual_check_<field>.json array) and the resource is saved.
- This script materializes each resource into ena_manual_<field>.jsonl, deduped
  by project_accession.
- It only READS manual_check_*.json and WRITES ena_manual_*.jsonl; it never
  touches ena_llm_infer_*.jsonl (that is final_merge's job, which reads
  ena_manual_* and applies the dual-axis priority).

Schema of each object in manual_check_<field>.json:
  project_accession   str   (required) ENA project accession
  field               str   (required) country | date | host  (MUST match filename field)
  value               list  (required) e.g. ["Gambia"] or ["Indonesia","Fiji"];
                                 for date: ["2019"]; for host: ["soil"]
  confidence          str   (required) manual entries are forced "high"
  source              str   (required) "manual"
  method              str   (required) "manual"
  content_reliability str   (optional) "high" (direct) | "medium"
                                 (institution_inferred, weaker); axis-A label
  evidence_basis      str   (optional) "direct" | "institution_inferred"
  note                str   (optional) English evidence chain (provenance)

Country names: canonical English (e.g. Korea; "Hong Kong, China" / "Taiwan, China"
per sovereignty rules; HK/TW/MO suffixed ", China"). Multi-country => list of names.

Usage:
  python ena_load_manual.py [--srcdir .manual]   # 默认从 .manual 读，写 ena_manual_<field>.jsonl 到 .tmp
"""
import json, os, argparse, collections, glob, sys
from datetime import datetime

VALID_FIELDS = {"country", "date", "host"}

# 目录基准：本脚本位于 <replan>/.script/，父目录即 replan 根目录
REPLAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .replan
MANUAL_DIR = os.path.join(REPLAN_ROOT, ".manual")
TMP_DIR = os.path.join(REPLAN_ROOT, ".tmp")
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


def main():
    ap = argparse.ArgumentParser(
        description="Materialize manual_check_<field>.json -> ena_manual_<field>.jsonl")
    ap.add_argument("--srcdir", default=MANUAL_DIR,
                    help="manual_check_<field>.json 所在目录（默认 .manual）")
    args = ap.parse_args()
    _replan_log("ena_load_manual --srcdir %s" % args.srcdir)

    if not os.path.isdir(args.srcdir):
        raise SystemExit(f"missing dir: {args.srcdir}")

    # discover per-field resources: manual_check_<field>.json
    resources = {}
    for p in sorted(glob.glob(os.path.join(args.srcdir, "manual_check_*.json"))):
        base = os.path.basename(p)
        fld = base[len("manual_check_"):-len(".json")]
        if fld not in VALID_FIELDS:
            print(f"  skip (unknown field) {base}", file=sys.stderr)
            continue
        resources[fld] = p

    if not resources:
        raise SystemExit(f"no manual_check_<field>.json found in {args.srcdir}")

    by_field = collections.defaultdict(dict)
    for fld, p in resources.items():
        with open(p, encoding="utf-8") as f:
            try:
                arr = json.load(f)
            except Exception as e:
                raise SystemExit(f"bad JSON in {p}: {e}")
        if not isinstance(arr, list):
            raise SystemExit(f"{p} must be a JSON array of objects")
        for i, o in enumerate(arr):
            if not isinstance(o, dict):
                raise SystemExit(f"{p}[{i}] not an object")
            for k in ("project_accession", "field", "value", "confidence"):
                if k not in o:
                    raise SystemExit(f"{p}[{i}] missing required key '{k}'")
            if o["field"] != fld:
                raise SystemExit(f"{p}[{i}] field={o['field']!r} != filename field {fld!r}")
            if not isinstance(o["value"], list):
                o["value"] = [o["value"]]
            # normalize optional fields
            o.setdefault("source", "manual")
            o.setdefault("method", "manual")
            o.setdefault("content_reliability", "high")
            o.setdefault("evidence_basis", "direct")
            acc = o["project_accession"]
            if acc in by_field[fld]:
                raise SystemExit(f"duplicate project_accession {acc} in field '{fld}'")
            by_field[fld][acc] = o

    stats = {}
    for fld in sorted(by_field):
        outp = os.path.join(TMP_DIR, f"ena_manual_{fld}.jsonl")
        with open(outp, "w", encoding="utf-8") as w:
            for acc in sorted(by_field[fld]):
                w.write(json.dumps(by_field[fld][acc], ensure_ascii=False) + "\n")
        nb = collections.Counter(o.get("evidence_basis", "direct") for o in by_field[fld].values())
        stats[fld] = {"n": len(by_field[fld]), "by_evidence_basis": dict(nb),
                      "src": os.path.basename(resources[fld])}
        print(f"  wrote {outp}: {len(by_field[fld])} entries {dict(nb)}")

    print("OK " + json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
