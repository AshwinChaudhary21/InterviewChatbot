# app.py
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from typing import List
import globals  # shared global variable storage

# Import postgres helpers
from postgres import init_postgres, save_candidate_and_answers

# Import backend helpers
from server import generate_questions, parse_tech_input


# ---------------------------------------------------------------------------
# Local JSON fallback (used if PostgreSQL is unavailable)
# ---------------------------------------------------------------------------
def save_local(candidate: dict, answers: list) -> str:
    import json
    from datetime import datetime
    from pathlib import Path

    out = {
        "candidate": candidate,
        "answers": answers,
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    path = Path("local_candidates.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]") if path.exists() else []
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    data.append(out)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"local-{len(data)}"


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="TalentScout", page_icon="🧑‍💻", layout="wide")


def safe_rerun():
    st.rerun()


# ---------------------------------------------------------------------------
# Initialize PostgreSQL once (non-fatal — warn only on first load)
# ---------------------------------------------------------------------------
if "pg_init_attempted" not in st.session_state:
    st.session_state.pg_init_attempted = True
    try:
        init_postgres()
        st.session_state.pg_available = True
    except Exception as e:
        st.session_state.pg_available = False
        st.warning(f"PostgreSQL init warning (falling back to local save): {e}")

pg_available: bool = st.session_state.get("pg_available", False)


# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
defaults = {
    "candidate": {},
    "generated_questions": {},
    "question_texts": {},
    "answers": {},
    "chat_history": [],
    "step": "collect_info",   # collect_info -> tech_stack -> show_questions -> finished
    "terminated": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def add_message(speaker: str, text: str):
    st.session_state.chat_history.append({"speaker": speaker, "text": text})


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🧑‍💻 TalentScout")
st.write(
    "I will collect your details and tech stack to run an online assessment "
    "checking your proficiency in the technologies you mention. "
    "Fill in the form on the right to get started."
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
left, right = st.columns([2.5, 1])

# ---- LEFT — conversation + questions ----
with left:
    st.subheader("Conversation")
    if not st.session_state.chat_history:
        add_message("bot", "Hello! Please provide your details using the form on the right.")
    for msg in st.session_state.chat_history:
        if msg["speaker"] == "bot":
            st.markdown(f"**Bot:** {msg['text']}")
        else:
            st.markdown(f"**You:** {msg['text']}")
    st.markdown("---")

    # Show questions & answer text areas
    if st.session_state.generated_questions:
        st.header("Answer the questions")
        for tech, items in st.session_state.generated_questions.items():
            st.subheader(tech)
            for idx, item in enumerate(items, start=1):
                qkey = f"{tech}|||Question{idx}"   # use ||| separator to avoid collision
                question_text = item.get("question") if isinstance(item, dict) else str(item)
                if not question_text:
                    question_text = st.session_state.question_texts.get(qkey, "")
                st.markdown(f"**Q{idx}.** {question_text}")
                textarea_key = qkey + "_ta"
                prev = st.session_state.answers.get(qkey, "")
                ans = st.text_area(
                    label=f"Your answer for {tech} — Q{idx}",
                    value=prev,
                    key=textarea_key,
                    height=140,
                )
                st.session_state.answers[qkey] = ans
                focus = item.get("ideal_answer_focus", "") if isinstance(item, dict) else ""
                if focus:
                    st.caption("Ideal answer focus: " + focus)

        if st.button("Finish & Submit Answers"):
            candidate = st.session_state.candidate.copy() if st.session_state.candidate else {}
            candidate["tech_stack"] = globals.techstack if getattr(globals, "techstack", None) else candidate.get("tech_stack", [])

            answers_list = []
            for key, ans_text in st.session_state.answers.items():
                q_text = st.session_state.question_texts.get(key, "")
                # split on ||| separator
                tech_part = key.split("|||", 1)[0] if "|||" in key else "General"
                answers_list.append({
                    "tech":     tech_part,
                    "question": q_text,
                    "answer":   ans_text,
                })

            if pg_available:
                try:
                    cid = save_candidate_and_answers(candidate, answers_list)
                    st.success(f"Saved to PostgreSQL. Candidate id: {cid}")
                    add_message("bot", "Thank you — your answers have been saved.")
                    st.session_state.step = "finished"
                    st.session_state.terminated = True
                except Exception as e:
                    st.error(f"Failed to save answers to PostgreSQL: {e}")
                    try:
                        lid = save_local(candidate, answers_list)
                        st.warning(f"Saved to local file as fallback. id: {lid}")
                        add_message("bot", "Saved locally as fallback after DB error.")
                        st.session_state.step = "finished"
                        st.session_state.terminated = True
                    except Exception as ex:
                        st.error(f"Also failed to save locally: {ex}")
            else:
                try:
                    lid = save_local(candidate, answers_list)
                    st.success(f"Saved locally. Candidate id: {lid}")
                    add_message("bot", "Thank you — your answers have been saved locally.")
                    st.session_state.step = "finished"
                    st.session_state.terminated = True
                except Exception as e:
                    st.error(f"Failed to save answers locally: {e}")

    if st.session_state.terminated:
        st.success("Conversation ended. Thank you for participating.")
        cand = st.session_state.candidate
        if cand:
            st.markdown("#### Summary")
            st.markdown(f"**Name:** {cand.get('full_name','')}")
            st.markdown(f"**Email:** {cand.get('email','')}")
            st.markdown(f"**Phone:** {cand.get('phone','')}")
            st.markdown(f"**Experience:** {cand.get('years_exp','')} years")
            st.markdown(f"**Positions:** {', '.join(cand.get('desired_positions', []))}")
            st.markdown(f"**Tech Stack:** {', '.join(cand.get('tech_stack', []))}")
            st.markdown("---")
        st.stop()


# ---- RIGHT — forms ----
with right:
    st.subheader("Controls & Forms")

    cmd = st.text_input("Quick command (type 'exit' to stop):", key="cmd_input")
    if cmd:
        add_message("user", cmd)
        if cmd.strip().lower() in {"exit", "quit", "bye"}:
            add_message("bot", "Received exit command. Ending session. Good luck!")
            st.session_state.terminated = True
        else:
            add_message("bot", "Quick commands supported: `exit`.")

    # Step 1 — Candidate details
    if st.session_state.step == "collect_info":
        st.markdown("### Step 1 — Candidate details")
        with st.form("candidate_form"):
            full_name  = st.text_input("Full Name",           value=st.session_state.candidate.get("full_name", ""))
            email      = st.text_input("Email Address",       value=st.session_state.candidate.get("email", ""))
            phone      = st.text_input("Phone Number",        value=st.session_state.candidate.get("phone", ""))
            years_exp  = st.number_input("Years of Experience", min_value=0, max_value=80,
                                         value=st.session_state.candidate.get("years_exp", 0))
            desired_positions = st.text_area(
                "Desired Position(s) — comma separated",
                value=", ".join(st.session_state.candidate.get("desired_positions", [])),
            )
            location   = st.text_input("Current Location",   value=st.session_state.candidate.get("location", ""))
            submit     = st.form_submit_button("Save Details")

        if submit:
            form_errors = []
            if not full_name.strip():
                form_errors.append("Full name is required.")
            if "@" not in email or "." not in email:
                form_errors.append("Please enter a valid email address.")
            if len("".join(ch for ch in phone if ch.isdigit())) < 7:
                form_errors.append("Please enter a valid phone number (min 7 digits).")
            if not desired_positions.strip():
                form_errors.append("List at least one desired position.")
            if not location.strip():
                form_errors.append("Provide your current location.")

            if form_errors:
                for err in form_errors:
                    st.error(err)
            else:
                st.session_state.candidate = {
                    "full_name":         full_name.strip(),
                    "email":             email.strip(),
                    "phone":             phone.strip(),
                    "years_exp":         int(years_exp),
                    "desired_positions": [p.strip() for p in desired_positions.split(",") if p.strip()],
                    "location":          location.strip(),
                }
                add_message("bot", f"Thanks, {full_name.split()[0]}! Details saved. Now enter your tech stack.")
                st.session_state.step = "tech_stack"

    # Step 2 — Tech stack
    elif st.session_state.step == "tech_stack":
        st.markdown("### Step 2 — Tech stack")
        with st.form("tech_form"):
            langs      = st.text_area("Programming Languages (comma separated)",
                                      value=", ".join(st.session_state.candidate.get("languages", [])))
            frameworks = st.text_area("Frameworks (comma separated)",
                                      value=", ".join(st.session_state.candidate.get("frameworks", [])))
            dbs        = st.text_area("Databases (comma separated)",
                                      value=", ".join(st.session_state.candidate.get("databases", [])))
            tools      = st.text_area("Tools / DevOps / Cloud (comma separated)",
                                      value=", ".join(st.session_state.candidate.get("tools", [])))
            submit_tech = st.form_submit_button("Generate Questions (Groq)")

        if submit_tech:
            techstack: List[str] = []
            for s in (langs, frameworks, dbs, tools):
                techstack.extend(parse_tech_input(s))

            if not techstack:
                st.error("Please enter at least one technology.")
            else:
                st.session_state.candidate.update({
                    "languages":  parse_tech_input(langs),
                    "frameworks": parse_tech_input(frameworks),
                    "databases":  parse_tech_input(dbs),
                    "tools":      parse_tech_input(tools),
                })
                globals.techstack = techstack
                add_message("bot", f"Tech stack recorded: {', '.join(globals.techstack[:8])}")

                try:
                    with st.spinner("Generating questions via Groq — this may take a few seconds..."):
                        raw_q_map = generate_questions(globals.techstack)
                except Exception as e:
                    st.error(f"Failed to generate questions with Groq: {e}")
                    raw_q_map = {}

                # Normalize whatever shape Groq returned
                def normalize_q_map(q_map):
                    normalized = {}
                    if not q_map:
                        return normalized
                    for tech, items in q_map.items():
                        tech_label = str(tech)
                        new_list = []
                        if isinstance(items, str):
                            new_list.append({"question": items.strip(), "ideal_answer_focus": ""})
                        elif isinstance(items, (list, tuple)):
                            for it in items:
                                if isinstance(it, str):
                                    new_list.append({"question": it.strip(), "ideal_answer_focus": ""})
                                elif isinstance(it, dict):
                                    q = it.get("question") or it.get("q") or it.get("prompt") or ""
                                    if not q:
                                        q = next((str(v) for v in it.values() if isinstance(v, str)), str(it))
                                    focus = it.get("ideal_answer_focus") or it.get("focus") or ""
                                    new_list.append({"question": str(q).strip(), "ideal_answer_focus": str(focus).strip()})
                                else:
                                    new_list.append({"question": str(it).strip(), "ideal_answer_focus": ""})
                        else:
                            new_list.append({"question": str(items).strip(), "ideal_answer_focus": ""})
                        normalized[tech_label] = new_list
                    return normalized

                norm_q_map = normalize_q_map(raw_q_map)
                st.session_state.generated_questions = norm_q_map

                # Build flat question_texts map using ||| separator
                st.session_state.question_texts = {}
                for tech, items in norm_q_map.items():
                    for idx, item in enumerate(items, start=1):
                        key = f"{tech}|||Question{idx}"
                        st.session_state.question_texts[key] = item.get("question", "")

                st.success("Questions generated! Answer them on the left panel.")
                st.session_state.step = "show_questions"

    elif st.session_state.step == "show_questions":
        st.markdown("### Questions generated")
        st.write("Answer the questions on the left, then click **Finish & Submit Answers**.")

    elif st.session_state.step == "finished":
        st.markdown("### Finished")
        st.success("You have completed the assessment. Thanks!")


# ---------------------------------------------------------------------------
# Sidebar — session summary & reset
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Session Summary")
    cand = st.session_state.candidate
    if cand:
        st.markdown(f"**Name:** {cand.get('full_name', '')}")
        st.markdown(f"**Email:** {cand.get('email', '')}")
        st.markdown(f"**Phone:** {cand.get('phone', '')}")
        st.markdown(f"**Experience:** {cand.get('years_exp', '')} yrs")
        st.markdown(f"**Positions:** {', '.join(cand.get('desired_positions', []))}")
        st.markdown("---")
        st.markdown("**Tech Stack**")
        st.markdown(", ".join(globals.techstack) or "—")
    else:
        st.write("No candidate data yet.")

    st.markdown("---")
    db_status = "✅ PostgreSQL" if pg_available else "⚠️ Local file fallback"
    st.caption(f"Storage: {db_status}")

    if st.button("Reset Session"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        globals.techstack = []
        safe_rerun()
