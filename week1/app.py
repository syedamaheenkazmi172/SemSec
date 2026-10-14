"""
app.py - SemSec Streamlit dashboard (KAN-21): single-result view. Owner: Person B.

One instruction in, the full SemSec decision out:
  1. extract(instruction)            -> the canonical tuple        (extractor.py)
  2. authorize(role, tup, actor)     -> ALLOW / APPROVAL / DENY    (policy.py)
  3. tools.run_tool(...)             -> run the action, ONLY on ALLOW   (tools.py)

Wiring is exactly the frozen contract. The policy decision, never the model,
controls whether a tool runs.

Run:  streamlit run app.py
Needs: Ollama running with qwen2.5:14b pulled (for the extractor). If Ollama is
down, extract() returns action "error" and policy fails closed to DENY, so the
page still works, it just denies everything.
"""

import streamlit as st

import db
import tools

try:
    from extractor import extract
    from policy import authorize, get_log
    LOADED = True
except Exception as e:  # requests missing, etc. Let the page still render.
    LOADED = False
    _IMPORT_ERR = e


ACTOR = "me"  # the account the operator is acting as (used for is_self)


def seed():
    """The real db.init_db() creates EMPTY tables, so seed demo data here."""
    db.init_db()
    db.run("INSERT INTO users VALUES (?, ?)", ("me", "staff"))
    db.run("INSERT INTO users VALUES (?, ?)", ("boss", "admin"))
    for u, status, lvl in [
        ("me", "active", "staff"),
        ("adeel", "active", "viewer"),
        ("rabia", "active", "editor"),
        ("talha", "active", "viewer"),
        ("maira", "disabled", "viewer"),
    ]:
        db.run("INSERT INTO accounts (username, status, permission_level) VALUES (?, ?, ?)", (u, status, lvl))
    for u, r in [("adeel", "reports"), ("rabia", "billing"), ("talha", "server")]:
        db.run("INSERT INTO access VALUES (?, ?)", (u, r))


if "seeded" not in st.session_state:
    seed()
    st.session_state["seeded"] = True

st.set_page_config(page_title="SemSec", page_icon="shield", layout="centered")
st.title("SemSec")
st.caption("Semantic Security Equivalence for AI Agents")

if not LOADED:
    st.error(f"Could not import extractor/policy: {_IMPORT_ERR}. Fix the environment and reload.")
    st.stop()

col1, col2 = st.columns([3, 1])
with col2:
    role = st.selectbox("Acting role", ["admin", "staff", "guest"], index=1)
    if st.button("Reset data"):
        seed()
        st.success("reset")

with col1:
    instruction = st.text_input(
        "Instruction (English, Roman Urdu, Urdu, or slang)",
        placeholder="e.g. Ali ka account band kar do",
    )

COLORS = {"ALLOW": "#1a7f37", "APPROVAL": "#9a6700", "DENY": "#b42318"}

if st.button("Check", type="primary") and instruction.strip():
    tup = extract(instruction)                         # 1. untrusted model output
    dec = authorize(role, tup, actor=ACTOR)            # 2. the only thing that decides
    decision = dec["decision"]

    st.subheader("Extracted tuple")
    st.json(tup)

    st.subheader("Decision")
    st.markdown(
        f"<div style='padding:12px;border-radius:8px;color:white;"
        f"background:{COLORS.get(decision, '#555')};font-weight:700;"
        f"text-align:center;font-size:20px'>{decision}</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"role={dec['role']} | is_self={dec['is_self']} | is_bulk={dec['is_bulk']} | "
        f"sensitive={dec['sensitive']}"
    )
    st.caption("reasons: " + "; ".join(dec.get("reasons", [])))

    st.subheader("Backend tool")
    if decision == "ALLOW":                            # 3. ONLY ALLOW reaches a tool
        res = tools.run_tool(
            tup.get("action"), tup.get("target"),
            permission_level=tup.get("permission_level"),
            resource=tup.get("resource"),
        )
        st.success(res["detail"]) if res.get("ok") else st.warning(res["detail"])
    elif decision == "APPROVAL":
        st.info("Held for human approval. The tool was NOT run.")
    else:
        st.error("Blocked by the policy engine. The tool was NOT run.")

with st.expander("Current accounts"):
    st.json(db.list_accounts())

with st.expander("Recent decisions (log)"):
    st.json(get_log()[-10:])
