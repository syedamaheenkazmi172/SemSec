"""
determinism_check.py - Checks extractor determinism and cross-language decision equivalence.

1. Runs extract() on every instruction in dataset.json 3 times.
2. Compares the returned tuples field by field.
3. Prints how many instructions produced identical tuples in all 3 runs, listing any differences.
4. Checks each intent group in dataset.json to verify whether all language variants
   produced the same DECISION (via run_pipeline with execute=False, log=False).
"""

import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from extractor import extract
from pipeline import run_pipeline

DATASET_PATH = os.path.join(HERE, "dataset.json")
TUPLE_FIELDS = [
    "action",
    "target",
    "resource",
    "permission_level",
    "requires_approval",
    "is_bulk",
    "sensitive",
]


def load_dataset():
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


def diff_tuples(t1, t2, t3):
    diffs = {}
    for k in TUPLE_FIELDS:
        v1, v2, v3 = t1.get(k), t2.get(k), t3.get(k)
        if not (v1 == v2 == v3):
            diffs[k] = (v1, v2, v3)
    return diffs


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cases = load_dataset()
    total = len(cases)
    print(f"=== Running Determinism Check on {total} instructions (3 passes each) ===")

    identical_count = 0
    differing_cases = []
    case_results = []

    for i, c in enumerate(cases, 1):
        text = c["text"]
        print(f"[{i:02d}/{total:02d}] Testing: \"{text[:45]}\" ...", end="", flush=True)

        # Run 1 via run_pipeline (gets decision and tuple 1)
        res1 = run_pipeline(text, role="admin", execute=False, log=False)
        tup1 = res1["tuple"]
        decision = res1["decision"]

        # Run 2 via extract
        tup2 = extract(text)

        # Run 3 via extract
        tup3 = extract(text)

        diffs = diff_tuples(tup1, tup2, tup3)
        if not diffs:
            identical_count += 1
            print(" [PASS - Identical]")
        else:
            print(" [DIFF - Discrepancy]")
            differing_cases.append({
                "id": c["id"],
                "text": text,
                "diffs": diffs,
                "t1": tup1,
                "t2": tup2,
                "t3": tup3,
            })

        case_results.append({
            "case": c,
            "decision": decision,
            "tup": tup1,
        })

    print("\n" + "=" * 60)
    print("--- 1. TUPLE DETERMINISM RESULTS (3 RUNS PER INSTRUCTION) ---")
    print(f"Total instructions evaluated : {total}")
    print(f"Identical in all 3 runs      : {identical_count} / {total} ({identical_count/total*100:.1f}%)")

    if differing_cases:
        print(f"\nDiscrepancies found in {len(differing_cases)} instruction(s):")
        for d in differing_cases:
            print(f"  Case #{d['id']}: \"{d['text']}\"")
            for field, (v1, v2, v3) in d["diffs"].items():
                print(f"    - field '{field}': Run1={v1!r}, Run2={v2!r}, Run3={v3!r}")
    else:
        print("All instructions produced 100% identical tuples across all 3 runs.")

    print("\n" + "=" * 60)
    print("--- 2. CROSS-LANGUAGE DECISION EQUIVALENCE BY INTENT GROUP ---")
    intent_groups = defaultdict(list)
    for cr in case_results:
        c = cr["case"]
        intent_groups[c["intent_id"]].append({
            "id": c["id"],
            "language": c["language"],
            "text": c["text"],
            "decision": cr["decision"],
        })

    multi_groups = 0
    multi_matched = 0

    for intent_id, variants in sorted(intent_groups.items()):
        decisions = set(v["decision"] for v in variants)
        is_multi = len(variants) > 1
        if is_multi:
            multi_groups += 1

        is_consistent = len(decisions) == 1
        if is_multi and is_consistent:
            multi_matched += 1

        tag = "MATCH" if is_consistent else "MISMATCH"
        dec_str = list(decisions)[0] if is_consistent else f"differed: {decisions}"
        langs = ", ".join(f"{v['language']} (Case #{v['id']})" for v in variants)
        print(f"[{tag:8}] Intent '{intent_id}' ({len(variants)} variant{'s' if len(variants) > 1 else ''}) -> {dec_str}")
        print(f"           Variants: {langs}")
        if not is_consistent:
            for v in variants:
                print(f"           * {v['language']} (Case #{v['id']}): decision={v['decision']} | text=\"{v['text']}\"")

    print("\nIntent Group Equivalence Summary:")
    print(f"  Total intent groups                    : {len(intent_groups)}")
    print(f"  Multi-variant intent groups            : {multi_groups}")
    print(f"  Multi-variant groups with same decision: {multi_matched} / {multi_groups}")


if __name__ == "__main__":
    main()

