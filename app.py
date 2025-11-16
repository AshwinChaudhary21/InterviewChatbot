# app.py
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from typing import List
import globals  # shared global variable storage
from mongo import init_mongo, save_candidate_and_answers

# Import backend helpers (server.py should implement generate_questions and parse_tech_input)
try:
    from server import generate_questions, parse_tech_input  # type: ignore
except Exception:
    # fallback parse helper if server does not provide parse_tech_input
    def parse_tech_input(s: str) -> List[str]:
        import re
        if not s:
            return []
        return [item.strip() for item in re.split(r",|\n|;", s) if item.strip()]

# Optional Mongo integration (if you created mongo_store.py)
try:
    from mongo_store import init_mongo, save_candidate_and_answers  # type: ignore
    mongo_available = True
except Exception:
    mongo_available = False

st.set_page_config(page_title="TalentScout", page_icon="🧑‍💻", layout="wide")

# Safe rerun helper (best-effort)
def safe_rerun():
    try:
        st.experimental_rerun()
    except Exception:
        try:
            from streamlit.runtime.scriptrunner import RerunException
            raise RerunException()
        except Exception:
            return

# Initialize Mongo if available (non-fatal)
if mongo_available:
    try:
        init_mongo()
    except Exception as e:
        st.warning(f"Mongo init warning: {e}")

# Session state initialization
if "candidate" not in st.session_state:
    st.session_state.candidate = {}
if "generated_questions" not in st.session_state:
    st.session_state.generated_questions = {}
if "question_texts" not in st.session_state:
    st.session_state.question_texts = {}
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "step" not in st.session_state:
    st.session_state.step = "collect_info"  # collect_info -> tech_stack -> show_questions -> finished
if "terminated" not in st.session_state:
    st.session_state.terminated = False

def add_message(speaker: str, text: str):
    st.session_state.chat_history.append({"speaker": speaker, "text": text})

# Header / instructions
st.title("🧑‍💻TalentScout")
st.write(
    "I will collect your details and tech stack to get an online assessment to check your proficiency in the technologies you mentioned. "
    "Provide your information in the forms on the right."
)

# Layout: left conversation & questions, right forms
left, right = st.columns([2.5, 1])

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

    # Display generated questions (if any) and collect answers
    if st.session_state.generated_questions:
        st.header("Answer the questions")
        for tech, items in st.session_state.generated_questions.items():
            st.subheader(tech)
            for idx, item in enumerate(items, start=1):
                qkey = f"{tech} Question{idx}"
                question_text = item.get("question") if isinstance(item, dict) else str(item)
                if not question_text:
                    question_text = st.session_state.question_texts.get(qkey, "")
                st.markdown(f"**Q{idx}.** {question_text}")
                textarea_key = qkey + "_ta"
                prev = st.session_state.answers.get(qkey, "")
                ans = st.text_area(label=f"Your answer for {qkey}", value=prev, key=textarea_key, height=140)
                st.session_state.answers[qkey] = ans
                # show ideal focus if present
                focus = item.get("ideal_answer_focus", "") if isinstance(item, dict) else ""
                if focus:
                    st.caption("Ideal answer focus: " + focus)

        if st.button("Finish & Submit Answers"):
            # Build candidate dict and answers list
            candidate = st.session_state.candidate.copy() if st.session_state.candidate else {}
            # Ensure tech_stack is present — prefer globals.techstack
            candidate["tech_stack"] = globals.techstack if getattr(globals, "techstack", None) else candidate.get("tech_stack", [])

            answers_list = []
            for key, ans_text in st.session_state.answers.items():
                q_text = st.session_state.question_texts.get(key, "")
                tech_part = key.split("__", 1)[0] if "__" in key else "General"
                answers_list.append({
                    "tech": tech_part,
                    "question": q_text,
                    "answer": ans_text
                })

            # Save to Mongo if available, otherwise show a confirmation message
            if mongo_available:
                try:
                    candidate_id = save_candidate_and_answers(candidate, answers_list)
                    st.success(f"Saved successfully. Candidate id: {candidate_id}")
                    add_message("bot", "Thank you — your answers have been saved.")
                    st.session_state.step = "finished"
                    st.session_state.terminated = True
                except Exception as e:
                    st.error(f"Failed to save answers to MongoDB: {e}")
            else:
                # placeholder: user can implement their save routine
                st.success("Answers collected locally. (Mongo not configured—no persistent save performed.)")
                add_message("bot", "Thank you — your answers have been collected locally.")
                st.session_state.step = "finished"
                st.session_state.terminated = True

    if st.session_state.terminated:
        st.success("Conversation ended. Thank you for participating.")
        cand = st.session_state.candidate
        if cand:
            st.markdown("#### Summary")
            st.markdown(f"**Name:** {cand.get('full_name','')}")
            st.markdown(f"**Email:** {cand.get('email','')}")
            st.markdown(f"**Phone:** {cand.get('phone','')}")
            st.markdown(f"**Experience:** {cand.get('years_exp','')}")
            st.markdown(f"**Positions:** {', '.join(cand.get('desired_positions',[]))}")
            st.markdown(f"**Tech Stack:** {', '.join(cand.get('tech_stack', []))}")
            st.markdown("---")
        st.stop()

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

    # Candidate details form
    if st.session_state.step == "collect_info":
        st.markdown("### Step 1 — Candidate details")
        with st.form("candidate_form"):
            full_name = st.text_input("Full Name", value=st.session_state.candidate.get("full_name",""))
            email = st.text_input("Email Address", value=st.session_state.candidate.get("email",""))
            phone = st.text_input("Phone Number", value=st.session_state.candidate.get("phone",""))
            years_exp = st.number_input("Years of Experience", min_value=0, max_value=80, value=st.session_state.candidate.get("years_exp",0))
            desired_positions = st.text_area("Desired Position(s) — comma separated", value=",".join(st.session_state.candidate.get("desired_positions",[])))
            location = st.text_input("Current Location", value=st.session_state.candidate.get("location",""))
            submit = st.form_submit_button("Save Details")
        if submit:
            errors = []
            if not full_name.strip():
                errors.append("Full name required.")
            if "@" not in email or "." not in email:
                errors.append("Please enter a valid-looking email.")
            if len(''.join(ch for ch in phone if ch.isdigit())) < 7:
                errors.append("Please enter a valid phone number.")
            if not desired_positions.strip():
                errors.append("List at least one desired position.")
            if not location.strip():
                errors.append("Provide your current location.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                st.session_state.candidate = {
                    "full_name": full_name.strip(),
                    "email": email.strip(),
                    "phone": phone.strip(),
                    "years_exp": int(years_exp),
                    "desired_positions": [p.strip() for p in desired_positions.split(",") if p.strip()],
                    "location": location.strip()
                }
                add_message("bot", f"Thanks, {full_name.split()[0]}. Candidate details saved. Next — tech stack.")
                st.session_state.step = "tech_stack"

    # Tech stack form: writes to globals.techstack (replaces all_techs)
    elif st.session_state.step == "tech_stack":
        st.markdown("### Step 2 — Tech stack")
        with st.form("tech_form"):
            langs = st.text_area("Programming Languages (comma separated)", value=",".join(st.session_state.candidate.get("languages",[])))
            frameworks = st.text_area("Frameworks (comma separated)", value=",".join(st.session_state.candidate.get("frameworks",[])))
            dbs = st.text_area("Databases (comma separated)", value=",".join(st.session_state.candidate.get("databases",[])))
            tools = st.text_area("Tools / DevOps / Cloud (comma separated)", value=",".join(st.session_state.candidate.get("tools",[])))
            submit_tech = st.form_submit_button("Generate Questions (Groq)")
        if submit_tech:
            techstack: List[str] = []
            for s in (langs, frameworks, dbs, tools):
                parsed = parse_tech_input(s)
                techstack.extend(parsed)

            if not techstack:
                st.error("Please enter at least one technology.")
            else:
                # Update candidate tech fields and global techstack
                st.session_state.candidate.update({
                    "languages": parse_tech_input(langs),
                    "frameworks": parse_tech_input(frameworks),
                    "databases": parse_tech_input(dbs),
                    "tools": parse_tech_input(tools),
                })

                # --- update the global techstack as requested ---
                globals.techstack = techstack

                add_message("bot", f"Tech stack recorded: {', '.join(globals.techstack[:8])}")

                # Call Groq-powered generator (server.generate_questions) and robustly normalize
                try:
                    with st.spinner("Generating questions via Groq — this may take a few seconds..."):
                        raw_q_map = generate_questions(globals.techstack)
                except Exception as e:
                    st.error(f"Failed to generate questions with Groq: {e}")
                    raw_q_map = {}

                # Normalization helper
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
                                    if not isinstance(focus, str):
                                        focus = str(focus)
                                    new_list.append({"question": q.strip(), "ideal_answer_focus": focus.strip()})
                                else:
                                    new_list.append({"question": str(it).strip(), "ideal_answer_focus": ""})
                        else:
                            new_list.append({"question": str(items).strip(), "ideal_answer_focus": ""})

                        normalized[tech_label] = new_list
                    return normalized

                norm_q_map = normalize_q_map(raw_q_map)
                st.session_state.generated_questions = norm_q_map

                # create flat mapping for question texts
                st.session_state.question_texts = {}
                for tech, items in norm_q_map.items():
                    for idx, item in enumerate(items, start=1):
                        key = f"{tech}__q{idx}"
                        st.session_state.question_texts[key] = item.get("question", "")

                st.success("Questions generated. Answer them on the left panel.")
                st.session_state.step = "show_questions"

    elif st.session_state.step == "show_questions":
        st.markdown("### Questions generated")
        st.write("Questions are displayed on the left. Answer them and click 'Finish & Submit Answers' when done.")

    elif st.session_state.step == "finished":
        st.markdown("### Finished")
        st.success("Thanks — you have finished the interview questions.")

# Sidebar summary and reset
with st.sidebar:
    st.header("Session Summary")
    cand = st.session_state.candidate
    if cand:
        st.markdown(f"**Name:** {cand.get('full_name','')}")
        st.markdown(f"**Email:** {cand.get('email','')}")
        st.markdown(f"**Phone:** {cand.get('phone','')}")
        st.markdown(f"**Experience:** {cand.get('years_exp','')}")
        st.markdown(f"**Positions:** {', '.join(cand.get('desired_positions',[]))}")
        st.markdown("---")
        st.markdown("**Tech Stack (global)**")
        st.markdown(f"{', '.join(globals.techstack)}")
    else:
        st.write("No candidate data yet.")

    if st.button("Reset Session"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        # keep globals.techstack untouched unless you want to reset it too
        safe_rerun()
