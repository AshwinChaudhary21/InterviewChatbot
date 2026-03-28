# server.py
import os
import re
import json
from typing import List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

try:
    from groq import Groq
except Exception:
    Groq = None  # graceful fallback when library is not installed

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = None
if Groq and GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception:
        groq_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_tech_input(s: str) -> List[str]:
    """Split a comma/newline/semicolon-separated string into a clean list."""
    if not s:
        return []
    return [item.strip() for item in re.split(r",|\n|;", s) if item.strip()]


_PROMPT_TEMPLATE = """You are a senior technical interviewer. For each technology in the list below, generate **between 3 and 5** open-ended technical interview questions that deeply test practical proficiency (no trivial/yes-no questions).
Return the result as strict JSON only, with the exact top-level structure:

{{
  "<TECH_NAME_1>": [
    {{
      "question": "<question text>",
      "ideal_answer_focus": "<one-sentence bullet points of what the interviewer should look for (optional)>"
    }},
    ...
  ],
  "<TECH_NAME_2>": [ ... ]
}}

Requirements:
- Produce **JSON only** (no surrounding commentary, no markdown, no code fences).
- Each technology must have 3–5 questions.
- Questions must be unique, relevant, and practical (prefer real-world scenarios, debugging, design, performance, and tradeoffs).
- Keep each "ideal_answer_focus" concise (<= 25 words). It can be empty string if not needed.
- Each question should be answerable succinctly (within 2-3 lines).

Technologies: {tech_list}
"""


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that some models add around JSON."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _call_groq_for_questions(techs: List[str], max_tokens: int = 2000, temperature: float = 0.7) -> str:
    if not groq_client:
        raise RuntimeError(
            "Groq client not configured. Install `groq` and set GROQ_API_KEY in your .env file."
        )
    tech_list = ", ".join(techs)
    prompt = _PROMPT_TEMPLATE.format(tech_list=tech_list)
    messages = [
        {"role": "system", "content": "You are a precise JSON-producing assistant. Output JSON only, no markdown, no code fences."},
        {"role": "user", "content": prompt},
    ]
    resp = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        return resp.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"Groq response parsing failed: {e}")


def generate_questions(techs: List[str]) -> Dict[str, List[Dict[str, str]]]:
    """
    Given a list of tech strings, return:
        tech_name -> [ { "question": "...", "ideal_answer_focus": "..." }, ... ]
    Raises RuntimeError on failure.
    """
    if not techs:
        return {}

    techs_clean = [t.strip() for t in techs if t and t.strip()]
    if not techs_clean:
        return {}

    # Scale max_tokens with number of techs (each tech ~300 tokens), cap at 4000
    max_tokens = min(300 * len(techs_clean) + 200, 4000)

    raw = _call_groq_for_questions(techs_clean, max_tokens=max_tokens)

    # Strip markdown code fences before parsing
    raw_clean = _strip_code_fences(raw)

    try:
        parsed = json.loads(raw_clean)
    except json.JSONDecodeError:
        raise RuntimeError(
            "Groq did not return valid JSON. Raw output:\n\n" + raw
        )

    out: Dict[str, List[Dict[str, str]]] = {}
    for tech in techs_clean:
        if tech not in parsed or not isinstance(parsed[tech], list):
            raise RuntimeError(
                f"Groq JSON missing expected key for tech: {tech!r}\n\nRaw output:\n\n{raw}"
            )
        qs = []
        for item in parsed[tech]:
            if isinstance(item, dict) and "question" in item:
                q_text = str(item.get("question", "")).strip()
                focus = str(item.get("ideal_answer_focus", "") or "").strip()
                qs.append({"question": q_text, "ideal_answer_focus": focus})
        if len(qs) < 3:
            raise RuntimeError(
                f"Groq returned fewer than 3 questions for {tech!r}. Raw output:\n\n{raw}"
            )
        out[tech] = qs[:5]

    return out