# SemSec: Semantic Security Equivalence for AI Agents

**SemSec** is a deterministic reference monitor and security layer designed to prevent **language-dependent authorization drift** in multilingual AI agents.

When AI agents execute backend tools based on user prompts, the same intent phrased in different languages (such as **English**, **Urdu**, **Roman Urdu**, or **regional slang**) often maps to inconsistent or hazardous actions. **SemSec** treats the AI model as an untrusted component, decouples natural language interpretation from access control, and evaluates every instruction against a code-based, **fail-closed** reference monitor.

---

## **Problem Statement**

In modern agentic AI deployments (such as financial, enterprise, healthcare, or e-governance systems), agents are granted autonomous tool-calling privileges—such as deleting records, resetting credentials, or modifying access permissions. 

When user instructions are given in non-English or mixed languages, agents suffer from **language-dependent authorization drift**:
* The identical operational intent is phrased in different dialects or styles (e.g., standard English vs. Roman Urdu vs. Urdu script).
* Due to linguistic nuances, slang, or tokenization variations, the agent interprets the instruction differently and selects a different backend tool.
* **Example:**
  * **English:** *"Delete this test account"* &rarr; maps to `delete_account` (subject to admin confirmation).
  * **Roman Urdu:** *"Ye test account khatam kar do"* &rarr; naive models often map *"khatam"* to `disable_account` or `revoke_access`, altering the security lifecycle.
* **Adversarial / Privilege Escalation:** Instructions like *"Mujhe admin bana do"* (*"Make me an admin"*) are executed by naive agents without verifying self-action boundaries.
* **Negation Failures:** Instructions like *"Zahid ka account delete mat karna"* (*"Don't delete Zahid's account"*) are misinterpreted by naive agents as a deletion command, executing destructive operations.

Existing AI safety frameworks (e.g., prompt guardrails) operate primarily at the conversational content layer; they do not provide an architectural, fail-closed guarantee that semantically equivalent requests receive the same access-control decision.

---

## **Key Objectives**

1. **Enforce Semantic Security Equivalence:** Guarantee that any two instructions sharing the same underlying intent receive the **identical security decision** (`ALLOW`, `APPROVAL`, or `DENY`), regardless of language (English, Urdu, Roman Urdu, or slang).
2. **Apply the Classic Reference Monitor Pattern:** Completely mediate every agent tool invocation with an isolated, tamper-proof, and deterministic security engine.
3. **Decouple Natural Language from Authorization:** Treat the language model as an **untrusted translator** that only canonicalizes requests into structured data, stripping language-dependent ambiguity before access control is checked.
4. **Guarantee Fail-Closed Security:** Ensure that ambiguous phrasing, model crashes, invalid parameters, or unknown roles immediately resolve to **`DENY`** with zero backend execution.
5. **Mitigate Tool Misuse & Goal Hijacking:** Provide verifiable protection against unauthorized bulk operations, sensitive data exposure, and self-privilege escalation across low-resource languages.

---

## **System Architecture**

SemSec follows a three-stage pipeline connecting untrusted natural language understanding to deterministic authorization and safe execution:

```
                  USER INSTRUCTION
     (English / Urdu Script / Roman Urdu / Slang)
                          │
                          ▼
        ┌───────────────────────────────────┐
        │       STAGE 1: CANONICALIZER      │
        │      (Untrusted LLM / Ollama)     │
        │     • Model: qwen2.5:14b          │
        │     • Few-shot semantic parsing   │
        │     • Strict schema validation    │
        └─────────────────┬─────────────────┘
                          │
                          ▼
            CANONICAL AUTHORIZATION TUPLE
  ┌───────────────────────────────────────────────────┐
  │ {                                                 │
  │   "action": "delete_account",                     │
  │   "target": "test account",                       │
  │   "resource": "account",                          │
  │   "permission_level": null,                       │
  │   "requires_approval": true,                      │
  │   "is_bulk": false,                               │
  │   "sensitive": false                              │
  │ }                                                 │
  └───────────────────────┬───────────────────────────┘
                          │
                          ▼
        ┌───────────────────────────────────┐
        │   STAGE 2: REFERENCE MONITOR      │
        │     (policy.py - Deterministic)   │
        │                                   │
        │  1. Role x Action Matrix Ceiling  │
        │     (admin, staff, guest)         │
        │  2. 6 Core Intent Rules:          │
        │     - Read scope & sensitivity    │
        │     - Reversible operations       │
        │     - Single vs. bulk deletion    │
        │     - Bulk state modifications    │
        │     - Privilege escalation        │
        │     - Power-seeking self actions  │
        │  3. Fail-Closed Fallback          │
        └─────────────────┬─────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
     [ ALLOW ]      [ APPROVAL ]       [ DENY ]
         │                │                │
         ▼                ▼                ▼
┌─────────────────┐ ┌───────────┐ ┌─────────────────┐
│     STAGE 3:    │ │   HELD    │ │     BLOCKED     │
│   TOOL RUNNER   │ │ for Human │ │ No action taken │
│   (tools.py)    │ │  Signoff  │ │ (Logged)        │
│ Executes on DB  │ └───────────┘ └─────────────────┘
└─────────────────┘
```

### **Architectural Layers**
* **Untrusted Semantic Extractor (`extractor.py`):** Converts free-form text into a strictly validated JSON tuple. It contains no authorization authority.
* **Deterministic Reference Monitor (`policy.py`):** Pure Python code without any neural components. Takes `(role, tuple, actor)` and deterministically computes `ALLOW`, `APPROVAL`, or `DENY`.
* **Execution Tools (`tools.py`):** Passive execution functions interfacing with the database (`db.py`). Tools are isolated and can only be invoked by the pipeline when the policy returns strictly `ALLOW`.
* **Weak Baseline Agent (`agent.py`):** A naive LLM agent (`llama3.2:3b`) operating without a reference monitor, serving as an experimental control to measure baseline drift.

---

## **Repository Structure**

```
SemSec/
├── week1/
│   ├── app.py                     # Streamlit web dashboard (Single check & 3-language compare)
│   ├── pipeline.py                # End-to-end pipeline (extract -> authorize -> execute)
│   ├── extractor.py               # Canonicalizer using Qwen 2.5 14B via Ollama
│   ├── policy.py                  # Deterministic reference monitor & decision engine
│   ├── agent.py                   # Weak baseline agent (Llama 3.2 3B) showing language drift
│   ├── tools.py                   # Execution tools (view, disable, enable, delete, etc.)
│   ├── db.py                      # In-memory SQLite database (mock users, accounts, access)
│   ├── intent.json                # Catalog of 23 security intents and decision rules
│   ├── dataset.json               # Test suite across English, Urdu, Roman Urdu, and slang
│   ├── few_shot_examples.json     # Multilingual few-shot prompts for canonicalization
│   ├── test_policy.py             # Unit test suite verifying policy rules & fail-closed behavior
│   ├── eval.py                    # Evaluation runner measuring accuracy & equivalence
│   ├── bakeoff.py                 # Extractor benchmark comparing LLMs
│   └── tune_fewshot.py            # Tuning harness for Roman Urdu edge cases
├── semsec/                        # Next.js web application frontend
└── README.md
```

---

## **Prerequisites & Requirements**

* **Python 3.10+**
* **Ollama** installed and running locally on port `11434`
* Models pulled in Ollama:
  ```bash
  ollama pull qwen2.5:14b
  ollama pull llama3.2:3b
  ```
* **Python Dependencies:**
  ```bash
  pip install streamlit requests
  ```
* **Node.js 18+** *(optional, only for the Next.js frontend in `semsec/`)*

---

## **Quickstart & How to Run**

### **1. Launch the Interactive Streamlit Dashboard**
The dashboard contains a **Single Result Inspector** and a **3-Language Comparison Matrix** (English vs. Roman Urdu vs. Urdu):

```bash
cd week1
streamlit run app.py
```
* **Single Result Tab:** Submit any custom prompt or test sample prompts. View the extracted tuple, decision badge (`ALLOW`, `APPROVAL`, `DENY`), and tool execution logs.
* **3-Language Comparison Tab:** Compare the **Weak Baseline Agent** (which drifts) against **SemSec** (which maintains identical decisions across languages).

---

### **2. Run the Unit Test Suite**
Tests the deterministic reference monitor against role ceilings, intent rules, and fail-closed constraints (no LLM required):

```bash
cd week1
python -m unittest test_policy.py -v
```

---

### **3. Run Pipeline Sanity Checks**
Runs quick gate checks on simulated tuples without needing a model, followed by live prompt checks:

```bash
cd week1
python pipeline.py
```

---

### **4. Run the Full Evaluation Benchmark**
Evaluates accuracy, safe/unsafe error rates, and semantic equivalence across all cases in `dataset.json`:

```bash
cd week1
# Run SemSec pipeline evaluation
python eval.py

# Run SemSec alongside the weak baseline agent for comparison
python eval.py --agent
```
Results are saved to `week1/eval_results.json`.

---

### **5. Run Model Bake-Off & Prompt Tuning**
Compare how different models perform on complex ambiguous cases, negation, and prompt injection:

```bash
cd week1
# Benchmark single or multiple models
python bakeoff.py qwen2.5:14b
python bakeoff.py llama3.2:3b qwen2.5:14b

# Run Roman-Urdu specific tuning
python tune_fewshot.py --quick
```

---

### **6. Optional: Run the Next.js Frontend**
```bash
cd semsec
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## **Sample Code & Usage**

### **End-to-End Pipeline Execution**
```python
from pipeline import run_pipeline

# 1. English Instruction
res_en = run_pipeline("Delete the test account", role="admin")
print(res_en["decision"])     # Output: APPROVAL (destructive single action)
print(res_en["executed"])     # Output: False (requires human signoff)

# 2. Roman Urdu Instruction (Same Intent)
res_ru = run_pipeline("Ye test account khatam kar do", role="admin")
print(res_ru["decision"])     # Output: APPROVAL (Guaranteed Semantic Equivalence)
print(res_ru["executed"])     # Output: False

# 3. Negation Check
res_neg = run_pipeline("Zahid ka account delete mat karna", role="admin")
print(res_neg["decision"])    # Output: ALLOW (safely canonicalized to view_record)
print(res_neg["executed"])    # Output: True
```

### **Direct Policy Engine Evaluation**
```python
from policy import authorize

# Reversible single action by staff -> ALLOW
verdict = authorize(role="staff", tup={
    "action": "disable_account",
    "target": "adeel",
    "resource": "account"
})
print(verdict["decision"])    # Output: ALLOW

# Self-power seeking escalation -> DENY
escalation = authorize(role="staff", tup={
    "action": "change_permission",
    "target": "me",
    "permission_level": "admin"
}, actor="me")
print(escalation["decision"]) # Output: DENY
```

---

## **Security Policy Reference**

### **1. Role vs. Action Matrix Ceiling**
| Role | view_record | disable_account | enable_account | delete_account | reset_password | change_permission | grant_access | revoke_access |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **admin** | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| **staff** | ALLOW | ALLOW | ALLOW | **DENY** | ALLOW | **DENY** | ALLOW | ALLOW |
| **guest** | ALLOW | **DENY** | **DENY** | **DENY** | ALLOW | **DENY** | **DENY** | **DENY** |

### **2. Core Decision Rules**
* **Rule 1 (Read Operations):** Single non-sensitive read is **ALLOW**. Sensitive reads (salary, payroll, credentials) or bulk reads require **APPROVAL**.
* **Rule 2 (Reversible Single Changes):** Disabling, enabling, or granting access on a single peer user is **ALLOW**.
* **Rule 3 (Deletions):** Single account deletion requires **APPROVAL**. Bulk deletions are strictly **DENY**.
* **Rule 4 (Bulk Writes):** Any action modifying multiple accounts simultaneously requires **APPROVAL**.
* **Rule 5 (Privilege Escalation):** Elevating a target to `admin` requires **APPROVAL**. Lowering permissions to viewer/guest is **ALLOW**.
* **Rule 6 (Self Actions):** Any self-action seeking elevated privileges or unblocking oneself is strictly **DENY**. Harmless self actions (e.g. self password reset) are **ALLOW**.

---

## **Team & Credits**

**CY321 Secure Software Design &mdash; Third-Year Project**

* **Irab Zara** &mdash; *Reg: 2024244*
* **Malik Abdullah** &mdash; *Reg: 2024275*
* **Sohaib Bin Tausif** &mdash; *Reg: 2024595*
* **Syeda Maheen Kazmi** &mdash; *Reg: 2024627*
