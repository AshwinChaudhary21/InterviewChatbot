# server.py (top section)
import os
import json
from typing import List, Dict, Any
from dotenv import load_dotenv
# Import groq client safely (won't raise import-time exceptions)
load_dotenv()

try:
    from groq import Groq
except Exception:
    Groq = None  # graceful fallback when library is not installed

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# create client only when possible, but guard against constructor errors
groq_client = None
if Groq and GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception:
        groq_client = None

# Helper: build prompt requesting strict JSON output
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
- Produce **JSON only** (no surrounding commentary, no markdown).
- Each technology must have 3–5 questions.
- Questions must be unique, relevant, and practical (prefer real-world scenarios, debugging, design, performance, and tradeoffs).
- Keep each "ideal_answer_focus" concise (<= 25 words). It can be empty string if not needed.
- Use the exact JSON structure above.
- Generate a list of questions that can be answered succinctly (within 2-3 lines). Each question should be clear and focused to ensure a precise answer. 

Technologies: {tech_list}
"""

def _call_groq_for_questions(techs: List[str], max_tokens: int = 900, temperature: float = 0.7) -> str:
    if not groq_client:
        raise RuntimeError(
            "Groq client not configured. Install `groq` and set GROQ_API_KEY environment variable."
        )
    tech_list = ", ".join(techs)
    prompt = _PROMPT_TEMPLATE.format(tech_list=tech_list)
    # Build a conversation with system + user to encourage structured output
    messages = [
        {"role": "system", "content": "You are a precise JSON-producing assistant."},
        {"role": "user", "content": prompt},
    ]
    # Call Groq chat completion
    resp = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",  # change model if you prefer another Groq model available to you
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    # Extract text content
    try:
        content = resp.choices[0].message.content
        return content
    except Exception as e:
        raise RuntimeError(f"Groq response parsing failed: {e}")

def generate_questions(techs: List[str]) -> Dict[str, List[Dict[str,str]]]:
    """
    Given a list of tech strings, return a mapping:
       tech_name -> [ { "question": "...", "ideal_answer_focus": "..." }, ... ]
    This function ALWAYS uses Groq. If Groq fails, it raises an exception.
    """
    if not techs:
        return {}

    # Normalize techs to simple strings
    techs_clean = [t.strip() for t in techs if t and t.strip()]
    if not techs_clean:
        return {}

    # Call Groq
    raw = _call_groq_for_questions(techs_clean)

    # Try to parse JSON directly. Groq should return JSON-only per prompt.
    try:
        parsed = json.loads(raw)
        # Validate shape: ensure each tech maps to a list of dicts with "question"
        out: Dict[str, List[Dict[str,str]]] = {}
        for tech in techs_clean:
            if tech in parsed and isinstance(parsed[tech], list):
                qs = []
                for item in parsed[tech]:
                    if isinstance(item, dict) and "question" in item:
                        q_text = str(item.get("question", "")).strip()
                        focus = str(item.get("ideal_answer_focus", "")).strip() if item.get("ideal_answer_focus") is not None else ""
                        qs.append({"question": q_text, "ideal_answer_focus": focus})
                # Ensure 3-5 items
                if len(qs) < 3:
                    raise ValueError(f"Groq returned fewer than 3 questions for {tech!r}")
                out[tech] = qs[:5]
            else:
                raise ValueError(f"Groq JSON missing expected key for tech: {tech!r}")
        return out
    except json.JSONDecodeError:
        # If Groq did not produce parseable JSON, surface a helpful error with original content
        raise RuntimeError("Groq did not return valid JSON. Raw output:\n\n" + raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Groq output: {e}\n\nRaw output:\n\n{raw}")
