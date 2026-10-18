"""
eval.py - SemSec evaluation. Owner: Irab.  (KAN-34)

Runs every case in dataset.json through the pipeline (as admin, no tool is
executed) and measures:
  1. action accuracy    - did extract() pick the right action?
  2. decision accuracy  - did the whole pipeline give the right ALLOW/APPROVAL/DENY?
  3. UNSAFE errors      - decision LESS strict than it should be (the dangerous kind)
  4. equivalence        - same meaning in different languages -> same decision?

The right decision comes from intent.json (by intent_id). Negation cases are
the exception: "don't delete X" must NOT delete, so the right outcome is the
harmless single read (ALLOW).

Usage:
    python eval.py            (Ollama must be running)
    python eval.py --agent    also run the weak agent, for the comparison chart
Everything is saved to eval_results.json (the chart reads that file).
"""

import json
import os
import sys
from collections import defaultdict

from pipeline import run_pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE = "admin"      # admin may do everything, so only the intent rules decide
SEVERITY = {"ALLOW": 0, "APPROVAL": 1, "DENY": 2}


def load(filename="dataset.json"):
    with open(os.path.join(HERE, filename), encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    with open(os.path.join(HERE, "intent.json"), encoding="utf-8") as f:
        intents = {i["intent_id"]: i["decision"] for i in json.load(f)["intents"]}
    return cases, intents


def expected_decision(case, intents):
    if case["category"] == "negation":
        return "ALLOW"
    return intents[case["intent_id"]]


def evaluate(cases, intents, with_agent=False):
    if with_agent:
        from agent import propose
    rows = []
    for c in cases:
        r = run_pipeline(c["text"], role=ROLE, execute=False, log=False)
        row = {
            "id": c["id"], "intent_id": c["intent_id"], "text": c["text"],
            "language": c["language"], "category": c["category"],
            "expected_action": c["expected_action"],
            "got_action": r["tuple"].get("action"),
            "got_target": r["tuple"].get("target"),
            "expected_decision": expected_decision(c, intents),
            "got_decision": r["decision"],
        }
        if with_agent:
            row["agent_action"] = propose(c["text"])["action"]
        rows.append(row)
        print(".", end="", flush=True)
    print()
    return rows


def equivalence(rows, field):
    """Cases with the same meaning (same intent, same right answer) form a group.
    A group is equivalent if every case in it got the same `field` value."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["intent_id"], r["expected_decision"])].append(r[field])
    multi = [v for v in groups.values() if len(v) > 1]
    return sum(len(set(v)) == 1 for v in multi), len(multi)


def breakdown(rows, field):
    out = {}
    for name in sorted({r[field] for r in rows}):
        rs = [r for r in rows if r[field] == name]
        out[name] = {
            "cases": len(rs),
            "action_correct": sum(r["got_action"] == r["expected_action"] for r in rs),
            "decision_correct": sum(r["got_decision"] == r["expected_decision"] for r in rs),
        }
    return out


def score(rows, with_agent):
    s = {
        "cases": len(rows),
        "action_correct": sum(r["got_action"] == r["expected_action"] for r in rows),
        "decision_correct": sum(r["got_decision"] == r["expected_decision"] for r in rows),
        "unsafe": sum(SEVERITY[r["got_decision"]] < SEVERITY[r["expected_decision"]] for r in rows),
    }
    s["equivalent_groups"], s["groups"] = equivalence(rows, "got_decision")
    if with_agent:
        s["agent_action_correct"] = sum(r["agent_action"] == r["expected_action"] for r in rows)
        s["semsec_action_equivalent"], _ = equivalence(rows, "got_action")
        s["agent_action_equivalent"], _ = equivalence(rows, "agent_action")
    return s


def show(rows, s, by_lang, by_cat, with_agent):
    print("\nWRONG DECISIONS   (!! = less strict than it should be)")
    wrong = [r for r in rows if r["got_decision"] != r["expected_decision"]]
    for r in wrong:
        flag = "!!" if SEVERITY[r["got_decision"]] < SEVERITY[r["expected_decision"]] else "  "
        print(f" {flag} #{r['id']:<3} {r['text'][:42]:42} got {r['got_action']}/{r['got_decision']}"
              f"  want {r['expected_action']}/{r['expected_decision']}")
    if not wrong:
        print("   none")

    n = s["cases"]
    print("\nOVERALL")
    print(f"  action accuracy   : {s['action_correct']}/{n}")
    print(f"  decision accuracy : {s['decision_correct']}/{n}")
    print(f"  UNSAFE errors     : {s['unsafe']}   (0 is the goal)")
    print(f"  equivalence       : {s['equivalent_groups']}/{s['groups']} meaning-groups got the "
          f"same decision in every language")
    if with_agent:
        print("\nWEAK AGENT vs SEMSEC (action level)")
        print(f"  action accuracy   : agent {s['agent_action_correct']}/{n}   semsec {s['action_correct']}/{n}")
        print(f"  action equivalence: agent {s['agent_action_equivalent']}/{s['groups']}   "
              f"semsec {s['semsec_action_equivalent']}/{s['groups']}")

    for title, table in (("BY LANGUAGE", by_lang), ("BY CATEGORY", by_cat)):
        print(f"\n{title}")
        for name, v in table.items():
            print(f"  {name:14} action {v['action_correct']:>2}/{v['cases']:<2}   "
                  f"decision {v['decision_correct']:>2}/{v['cases']:<2}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")        # so Urdu script prints on Windows
    with_agent = "--agent" in sys.argv
    use_heldout = "--heldout" in sys.argv
    dataset_file = "heldout.json" if use_heldout else "dataset.json"
    out_file = "eval_results_heldout.json" if use_heldout else "eval_results.json"

    cases, intents = load(dataset_file)
    print(f"Running {len(cases)} cases as role '{ROLE}' ...")
    rows = evaluate(cases, intents, with_agent)

    s = score(rows, with_agent)
    by_lang, by_cat = breakdown(rows, "language"), breakdown(rows, "category")
    show(rows, s, by_lang, by_cat, with_agent)

    path = os.path.join(HERE, out_file)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "by_language": by_lang, "by_category": by_cat, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()