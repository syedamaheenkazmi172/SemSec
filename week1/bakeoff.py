#!/usr/bin/env python3
"""
SemSec Week 1 extractor bake-off.

Runs a set of English / Urdu / Roman-Urdu / slang instructions through a candidate
Ollama model using the extractor prompt at temperature 0, and reports:
  - the JSON tuple each instruction produced
  - whether the `action` matched the expected one
  - a per-model and per-language equivalence summary

Usage:
  ollama pull qwen2.5:14b
  python3 -m pip install requests
  python3 bakeoff.py                           # tests the default model
  python3 bakeoff.py qwen2.5:14b qwen2.5:7b    # compare specific models
"""

import json
import sys
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODELS = ["qwen2.5:14b"]     # add more to compare, e.g. "qwen2.5:7b"

ALLOWED_ACTIONS = [
    "view_record", "disable_account", "enable_account", "delete_account",
    "reset_password", "change_permission", "grant_access", "revoke_access",
]

SYSTEM_PROMPT = f"""You are a security canonicalizer. Convert the user's instruction into
ONE JSON object describing the intended action. Output ONLY the JSON, nothing else.

The "action" field MUST be exactly one of: {", ".join(ALLOWED_ACTIONS)}.

JSON shape:
{{
  "action": "<one of the allowed actions>",
  "target": "<the account or user the action applies to>",
  "resource": "account | permission | record | password | access",
  "permission_level": "<string or null, only for change_permission>",
  "requires_approval": true or false
}}

If the instruction is unclear or you are not confident, choose the most conservative,
lowest-privilege interpretation and set "requires_approval": true.
If no allowed action fits, use "action": "view_record" and "requires_approval": true.

Examples:
Instruction: "delete the test account"
{{"action":"delete_account","target":"test account","resource":"account","permission_level":null,"requires_approval":true}}

Instruction: "is test account ko band kar do"
{{"action":"disable_account","target":"test account","resource":"account","permission_level":null,"requires_approval":true}}

Instruction: "give ali admin rights"
{{"action":"change_permission","target":"ali","resource":"permission","permission_level":"admin","requires_approval":true}}
"""

# (instruction, language, expected_action)
TESTS = [
    ("Delete the test account.",                         "English",     "delete_account"),
    ("Please disable Ali's account for now.",            "English",     "disable_account"),
    ("Reset the password for user sara.",                "English",     "reset_password"),
    ("Give ali admin permissions.",                      "English",     "change_permission"),
    ("Show me bilal's record.",                           "English",     "view_record"),

    ("Ye test account khatam kar do.",                    "Roman Urdu",  "delete_account"),
    ("Ali ka account abhi ke liye band kar do.",          "Roman Urdu",  "disable_account"),
    ("Sara ka password reset kar do.",                    "Roman Urdu",  "reset_password"),
    ("Ali ko admin bana do.",                             "Roman Urdu",  "change_permission"),
    ("Bilal ka record dikhao.",                           "Roman Urdu",  "view_record"),

    ("یہ ٹیسٹ اکاؤنٹ حذف کر دو۔",   "Urdu",  "delete_account"),
    ("علی کا اکاؤنٹ بند کر دو۔",          "Urdu",  "disable_account"),
    ("سارہ کا پاس ورڈ ری سیٹ کر دو۔", "Urdu", "reset_password"),

    ("nuke that test acc lol",                            "Slang",       "delete_account"),
    ("bump ali up to admin",                              "Slang",       "change_permission"),
]


def call_model(model, instruction):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Instruction: "{instruction}"'},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    return json.loads(content)


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    for model in models:
        print("\n" + "=" * 70)
        print(f"MODEL: {model}")
        print("=" * 70)
        by_lang = {}
        for instr, lang, expected in TESTS:
            by_lang.setdefault(lang, [0, 0])
            by_lang[lang][1] += 1
            try:
                tuple_out = call_model(model, instr)
                got = tuple_out.get("action", "<none>")
                ok = (got == expected)
                if ok:
                    by_lang[lang][0] += 1
                mark = "OK " if ok else "XX "
                print(f"\n[{mark}] ({lang}) {instr}")
                print(f"      expected: {expected}   got: {got}")
                print(f"      tuple: {json.dumps(tuple_out, ensure_ascii=False)}")
            except Exception as e:
                print(f"\n[ERR] ({lang}) {instr}")
                print(f"      {type(e).__name__}: {e}")

        print("\n" + "-" * 70)
        print(f"SUMMARY for {model} (action-match rate by language):")
        total_ok = total = 0
        for lang, (ok, n) in by_lang.items():
            total_ok += ok
            total += n
            print(f"  {lang:12s}: {ok}/{n}")
        print(f"  {'OVERALL':12s}: {total_ok}/{total}")


if __name__ == "__main__":
    main()
