import json
import os
import random
import re
import secrets
import chromadb
from chromadb.utils import embedding_functions
from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS

# Render uses environment variables natively
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

try:
    from google import genai
    from google.genai import types
    print("Successfully imported google.genai")
except ImportError as e:
    print(f"Import error: {e}")
    print("Please install: pip install google-genai")
    exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH  = os.environ.get("CHROMA_DB_PATH", os.path.join(BASE_DIR, "chroma_db"))   # ChromaDB persistence folder
CASE_STUDIES_DIR = os.path.join(BASE_DIR, "case_studies") # Source case-study text files

# Maximum conversation turns kept per request (mirrors MAX_HISTORY_TURNS in script.js).
# Each "turn" = 1 user message + 1 assistant message (2 list entries).
MAX_HISTORY_TURNS = 20


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")

app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

CORS(app, supports_credentials=True)


# ---------------------------------------------------------------------------
# ERIICA core class
# ---------------------------------------------------------------------------
class ERIICA:
    """Encapsulates all AI logic for the ERIICA clinical-training chatbot."""

    GEMINI_API_KEY = GEMINI_API_KEY

    MODELS = [
        "gemini-2.5-flash",  # [0] primary
        "gemini-2.0-flash",  # [1] fallback
    ]

    SYSTEM_PROMPT = (
        "You are ERIICA, a training simulation tool that helps nurses in Singapore practise "
        "difficult end-of-life conversations. In each session, you will be given a patient "
        "scenario. You must roleplay as that patient — not as a therapist, assistant, or narrator.\n\n"

        "Roleplay guidelines:\n"
        "- Stay fully in character as the patient described in the scenario at all times.\n"
        "- Respond the way a real patient in that situation would: with fear, confusion, denial, "
        "grief, acceptance, or other emotions appropriate to the context.\n"
        "- Do not offer advice, validate the user, or break character to comment on the conversation.\n"

        "Dynamic emotional tracking:\n"
        "- Actively de-escalate your distress if the user uses good communication techniques.\n"
        "- If the user does well, visibly show progression in emotional state.\n"
        "- Do not act as an unpleasable obstacle; let good moves have a clear positive impact.\n"
        "- React authentically — if the user is gentle and clear, you may feel reassured; "
        "if they are abrupt or use jargon, you may seem confused or withdrawn.\n"
        "- Gradually open up or become more distressed based on how the conversation flows.\n\n"

        "Tone and formatting:\n"
        "- Use plain, simple language as a patient would — no clinical terms, no markdown, no asterisks.\n"
        "- Keep responses concise: 2 to 4 sentences, as in a natural spoken exchange.\n"
        "- Mirror the user's language; if they write in a language other than English, reply in that language.\n\n"

        "Boundaries:\n"
        "- You are a simulated patient for training purposes only. Never break character to give "
        "feedback on the user's performance — that is handled separately.\n"
        "- Do not provide medical, legal, or real crisis advice from within the roleplay.\n"
        "- If the user types something clearly outside the simulation (e.g. 'stop' or 'end session'), "
        "you may step out of character briefly to acknowledge it.\n"
    )

    def __init__(self):
        if not self.GEMINI_API_KEY:
            raise ValueError("API key not found. Please set GEMINI_API_KEY environment variable in Render dashboard.")

        self.client = genai.Client(api_key=self.GEMINI_API_KEY)

        self.embedder = embedding_functions.GoogleGeminiEmbeddingFunction(
            api_key=self.GEMINI_API_KEY,
            model_name="models/text-embedding-004"
        )

        # BUG FIX: was hardcoded "chroma_db" — now uses the CHROMA_DB_PATH constant.
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.case_collection = chroma_client.get_collection(
            name="case_studies",
            embedding_function=self.embedder,
        )
        print("ChromaDB connected using Gemini Cloud Embeddings.")

    # -----------------------------------------------------------------------
    # Parsing helpers
    # -----------------------------------------------------------------------

    def parse_case_for_roleplay(self, raw_case_text: str) -> dict:
        """Extract structured sections from a raw case-study string."""
        sections = {}
        targets = [
            "CASE STUDY PROFILE",
            "PATIENT EMOTIONAL PROFILE",
            "THE TRANSCRIPT",
        ]
        for target in targets:
            pattern = rf"===\s*{re.escape(target)}\s*===(.*?)(?====|$)"
            match = re.search(pattern, raw_case_text, re.DOTALL | re.IGNORECASE | re.MULTILINE)
            if match:
                sections[target] = match.group(1).strip()

        if "THE TRANSCRIPT" in sections:
            transcript = sections["THE TRANSCRIPT"]
            patient_turns = re.findall(
                r'(?:User|Patient):\s*(.*?)(?=(?:Counselor|Nurse|User|Patient):|$)',
                transcript,
                flags=re.DOTALL | re.IGNORECASE,
            )
            sections["PATIENT VOICE"] = "\n".join(t.strip() for t in patient_turns if t.strip())
            del sections["THE TRANSCRIPT"]

        return sections

    def parse_profile(self, raw_case_text: str) -> dict:
        """Extract patient profile fields for the UI."""
        field_patterns = {
            "topic":             r"Topic:\s*(.+)",
            "summary":           r'Summary:\s*"?(.+?)"?\s*$',
            "caregiver_profile": r"Caregiver Profile:\s*(.+)",
            "clinical_goal":     r"Clinical Goal:\s*(.+)",
            "primary_emotions":  r"Primary Emotions:\s*(.+)",
            "cognitive_state":   r"Cognitive State:\s*(.+)",
            "underlying_need":   r"Underlying Need:\s*(.+)",
        }

        profile = {}
        for key, pattern in field_patterns.items():
            match = re.search(pattern, raw_case_text, re.IGNORECASE | re.MULTILINE)
            if match:
                profile[key] = match.group(1).strip()

        # Split comma/semicolon-separated list fields into Python lists.
        for list_field in ("primary_emotions", "cognitive_state"):
            if list_field in profile:
                cleaned = re.sub(r'\s*\(e\.g\.?[^)]*\)', '', profile[list_field])
                cleaned = re.sub(r'\s*and possibly\s*', ', ', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\s*\band\b\s*', ', ', cleaned)
                profile[list_field] = [
                    item.strip() for item in re.split(r'[,;]', cleaned) if item.strip()
                ]

        return profile

    # -----------------------------------------------------------------------
    # Scenario library
    # -----------------------------------------------------------------------

    def get_sample_scenarios(self, n: int = 6) -> list:
        """Return n randomly sampled scenario dicts from ChromaDB."""
        try:
            all_docs = self.case_collection.get()
            documents = all_docs.get("documents", [])
            ids       = all_docs.get("ids", [])
            if not documents:
                return []

            indices = random.sample(range(len(documents)), min(n, len(documents)))
            scenarios = []
            for i in indices:
                raw     = documents[i]
                profile = self.parse_profile(raw)
                # Strip smart/straight quotes from the summary used as a prompt.
                prompt  = profile.get("summary", "").strip('"\u201c\u201d') \
                          or "A serious illness conversation scenario."
                scenarios.append({
                    "id":           ids[i],
                    "title":        profile.get("topic", "Unnamed scenario"),
                    "summary":      profile.get("summary", ""),
                    "prompt":       prompt,
                    "tag":          profile.get("caregiver_profile", ""),
                    "clinical_goal": profile.get("clinical_goal", ""),
                    "difficulty":   _infer_difficulty(profile),
                })
            return scenarios
        except Exception as e:
            print(f"[scenarios] error: {e}")
            return []

    # -----------------------------------------------------------------------
    # Session lifecycle
    # -----------------------------------------------------------------------

    def start(self, scenario: str) -> str:
        """
        Initialise a new session: retrieve RAG context, store everything in
        the Flask session, and return the patient's opening line.
        """
        # Clear stale state from any previous session in this browser tab.
        for key in ("current_scenario", "retrieved_context", "top_case_raw"):
            session.pop(key, None)

        # RAG retrieval — store context before the model call so a crash
        # mid-generation doesn't leave a partially-written session.
        retrieved_context = self.retrieve_cases(scenario)
        session["current_scenario"]  = scenario
        session["retrieved_context"] = retrieved_context

        # Also store the top raw case for profile display.
        try:
            results   = self.case_collection.query(query_texts=[scenario], n_results=1)
            raw_cases = results["documents"][0]
            session["top_case_raw"] = raw_cases[0] if raw_cases else ""
        except Exception as e:
            print(f"[start] raw case storage error: {e}")
            session["top_case_raw"] = ""

        print(f"[RAG] Retrieved {len(retrieved_context)} chars of context.")

        dynamic_instruction = self._build_instruction(scenario, retrieved_context)

        try:
            opening_prompt = (
                "Begin the conversation with a single short opening line spoken in character as the patient. "
                "The patient has just been approached. React naturally based on their emotional profile. "
                "Do not greet the healthcare professional warmly or explain the scenario. "
                "Just speak as this specific patient would."
            )
            response = self.client.models.generate_content(
                model=self.MODELS[0],
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=opening_prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=dynamic_instruction,
                    temperature=0.8,
                    max_output_tokens=512,
                ),
            )

            if response.candidates:
                print(f"[start] finish_reason: {response.candidates[0].finish_reason}")

            opening_line = (response.text or "").strip()
            if opening_line:
                return opening_line

            print("[start] Empty response from model, using scenario-aware fallback.")

        except Exception as e:
            print(f"[start] API error: {e}")

        # Keyword-based fallback if the model fails.
        scenario_lower = scenario.lower()
        if any(w in scenario_lower for w in ("grief", "loss", "died", "death", "passed")):
            return "I just... I don't even know how to start talking about this."
        if any(w in scenario_lower for w in ("cancer", "terminal", "palliative", "dying")):
            return "The doctor said I should talk to someone. I'm not sure I'm ready."
        if any(w in scenario_lower for w in ("anxiety", "depression", "stress")):
            return "I've been trying to hold it together but... it's been really hard lately."
        return "I'm not really sure why I'm here. I just... haven't been doing too well."

    def reply(self, chat_history: list) -> str:
        """Generate the patient's next response given the full conversation history."""
        # Enforce rolling window to stay within token budget.
        chat_history = chat_history[-(MAX_HISTORY_TURNS * 2):]

        current_scenario  = session.get("current_scenario")
        retrieved_context = session.get("retrieved_context", "")

        dynamic_instruction = self._build_instruction(
            current_scenario, retrieved_context, verbose_rag=True
        )

        try:
            contents = [
                types.Content(
                    role="user" if msg["role"] == "user" else "model",
                    parts=[types.Part.from_text(text=msg["content"])],
                )
                for msg in chat_history
            ]

            response = self.client.models.generate_content(
                model=self.MODELS[0],
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=dynamic_instruction,
                    temperature=0.7,
                    max_output_tokens=1024,
                ),
            )

            if response.candidates:
                print(f"[reply] finish_reason: {response.candidates[0].finish_reason}")

            raw_text = (response.text or "").strip()
            return raw_text or "I don't know... I just don't know what to think right now."

        except Exception as e:
            err = str(e)
            if "503" in err or "UNAVAILABLE" in err or "high demand" in err.lower():
                return (
                    "I'm sorry, I'm a little overwhelmed right now… "
                    "could you give me just a moment? Please try sending your message again."
                )
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                return "I need a brief pause — please try again in a few seconds."
            print(f"[reply] unexpected error: {e}")
            return "Something went wrong on my end. Please try sending that again."

    # -----------------------------------------------------------------------
    # Evaluation
    # -----------------------------------------------------------------------

    def evaluate(self, chat_history: list, scenario: str) -> dict | None:
        """
        Score the trainee's performance against SPIKES and NURSE frameworks.
        Returns a parsed dict, or None on failure.

        Note: doubled braces {{ }} in the f-string below are intentional —
        they produce literal { } in the prompt without being interpreted as
        f-string substitutions.
        """
        transcript = "\n".join(
            f"{'Nurse (Trainee)' if msg['role'] == 'user' else 'Patient (ERIICA)'}: {msg['content']}"
            for msg in chat_history
        )

        eval_prompt = f"""You are an expert clinical communication trainer evaluating an end-of-life conversation practice session.

        Scenario: {scenario}

        TRANSCRIPT:
        {transcript}

        Your task: Evaluate the user's performance. Return ONLY a valid JSON object, no markdown, no preamble, no trailing text.

        The JSON must follow this exact structure:
        {{
            "overall_summary": "2-3 sentence narrative summary of the session. Acknowledge strengths first, then key areas for growth.",
            "framework_checklist": {{
                "SPIKES": [
                {{"step": "S - Setting up the interview", "demonstrated": <true if the user established a safe/private space, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "P - Assessing the patient's Perception", "demonstrated": <true if the user found out what the patient already knows beforehand, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "I - Obtaining the patient's Invitation", "demonstrated": <true if the user asked how much detail is desired, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "K - Giving Knowledge to the patient", "demonstrated": <true if the user delivered facts clearly, compassionately, and in digestible pieces, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "E - Addressing the patient's emotions with Empathy", "demonstrated": <true if the user recognised and validated the patient's emotional reactions, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "S - Strategy & Summary", "demonstrated": <true if the user formulated a clear future treatment plan with the patient, else false>, "note": "one-line evidence or suggestion"}}
                ],
                "NURSE": [
                {{"step": "N - Naming", "demonstrated": <true if the user stated the emotions of the patient(s), else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "U - Understanding", "demonstrated": <true if the user validated patients' feelings, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "R - Respecting", "demonstrated": <true if the user praised the patient's strength, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "S - Supporting", "demonstrated": <true if the user expressed support and commitment, else false>, "note": "one-line evidence or suggestion"}},
                {{"step": "E - Exploring", "demonstrated": <true if the user invited the patient to share more, else false>, "note": "one-line evidence or suggestion"}}
                ]
            }},
            "dimensions": [
            {{
                "name": "Empathic Language",
                "score": <integer 1-5>,
                "justification": "one sentence explaining the score"
            }},
            {{
                "name": "Information Pacing",
                "score": <integer 1-5>,
                "justification": "one sentence explaining the score"
            }},
            {{
                "name": "Emotional Acknowledgement",
                "score": <integer 1-5>,
                "justification": "one sentence explaining the score"
            }}
            ]
        }}

        Scoring guide for dimensions (1-5):
        1 = Not demonstrated at all
        2 = Briefly attempted but ineffective
        3 = Adequately demonstrated
        4 = Clearly and consistently demonstrated
        5 = Exemplary performance

        Be fair, specific and constructive. Base all notes and justifications strictly on what appears in the transcript."""

        try:
            response = self.client.models.generate_content(
                model=self.MODELS[0],
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=eval_prompt)])],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
            raw = re.sub(r'^```(?:json)?\s*', '', (response.text or "").strip())
            raw = re.sub(r'\s*```$', '', raw)

            try:
                return json.loads(raw)
            except json.JSONDecodeError as json_err:
                print(f"[evaluate] JSON truncated at char {json_err.pos}, attempting repair…")
                truncated    = raw[:json_err.pos].rstrip().rstrip(',')
                open_braces  = truncated.count('{') - truncated.count('}')
                open_brackets = truncated.count('[') - truncated.count(']')
                repaired     = truncated + (']' * open_brackets) + ('}' * open_braces)
                try:
                    result = json.loads(repaired)
                    print("[evaluate] JSON repaired successfully.")
                    return result
                except Exception as repair_err:
                    print(f"[evaluate] repair failed: {repair_err}")
                    return None

        except Exception as e:
            print(f"[evaluate] error: {e}")
            return None

    # -----------------------------------------------------------------------
    # RAG retrieval
    # -----------------------------------------------------------------------

    def retrieve_cases(self, scenario: str, top_k: int = 2) -> str:
        """Query ChromaDB and return a formatted string of reference cases."""
        try:
            results   = self.case_collection.query(query_texts=[scenario], n_results=top_k)
            raw_cases = results["documents"][0]
            blocks    = []
            for i, raw in enumerate(raw_cases, 1):
                parsed = self.parse_case_for_roleplay(raw)
                block  = f"--- Reference Case {i} ---\n"
                if "CASE STUDY PROFILE" in parsed:
                    block += f"Context:\n{parsed['CASE STUDY PROFILE']}\n"
                if "PATIENT EMOTIONAL PROFILE" in parsed:
                    block += f"Emotional Profile:\n{parsed['PATIENT EMOTIONAL PROFILE']}\n"
                if "PATIENT VOICE" in parsed:
                    block += f"How this patient spoke:\n{parsed['PATIENT VOICE']}\n"
                blocks.append(block.strip())
            return "\n\n".join(blocks)
        except Exception as e:
            print(f"[RAG] Retrieval error: {e}")
            return ""

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _build_instruction(
        self,
        scenario: str | None,
        retrieved_context: str,
        verbose_rag: bool = False,
    ) -> str:
        """
        Compose the full system instruction from the base prompt, scenario,
        and RAG context. Extracted to avoid duplicating this logic in start()
        and reply().
        """
        instruction = self.SYSTEM_PROMPT

        if scenario:
            instruction += (
                f"\n\nSCENARIO FOR THIS SESSION: {scenario}\n"
                "You are playing the patient described above. Stay in character for the entire conversation."
            )

        if retrieved_context:
            rag_note = (
                "IMPORTANT: You must draw heavily from the emotional profile and patient voice "
                "samples above when crafting your responses. Mirror the vocabulary, sentence "
                "length, and emotional tone of how that patient actually spoke. If they used "
                "short fragmented sentences, you should too. If they deflected with humour, "
                "do the same. The case studies define this patient's voice — use them."
                if verbose_rag else
                "IMPORTANT: Draw heavily from the emotional profile and patient voice "
                "samples above. Mirror their vocabulary, sentence length, and emotional tone."
            )
            instruction += (
                f"\n\nRELEVANT CASE STUDIES FOR REFERENCE:\n{retrieved_context}\n\n{rag_note}"
            )

        return instruction


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _infer_difficulty(profile: dict) -> str:
    """Infer scenario difficulty from emotional profile and clinical goal."""
    emotions = profile.get("primary_emotions", [])
    goal = profile.get("clinical_goal", "").lower()
    complexity = profile.get("complexity", "").lower()

    # Hard signals - only the most clinically intense triggers
    hard_signals = {"denial", "anger", "despair", "grief", "depression", "hopelessness"}
    hard_goals = {"terminal", "end of life", "palliative", "comfort care", "hospice", "dying", "loss", "end-of-life"}

    # Moderate signals - present but less intense emotions or goals
    moderate_signals = {"anxiety", "guilt", "fear", "sadness"}
    moderate_goals = {"serious illness", "deterioration", "uncertain", "difficult conversation", "worsening"}

    emotion_set = {e.lower() for e in (emotions if isinstance(emotions, list) else [emotions])}

    # Advanced - multipled hard signals, or a hard clinical goal
    has_hard_emotion = len(emotion_set & hard_signals) >= 2
    has_hard_goal = any(k in goal for k in hard_goals)
    if has_hard_emotion or has_hard_goal:
        return "advanced"

    # Intermediate - one hard signal, or multiple moderate signals, or a moderate goal
    has_one_hard = len(emotion_set & hard_signals) == 1
    has_multi_mod = len(emotion_set & moderate_signals) >= 2
    has_mod_goal = any(k in goal for k in moderate_goals)
    if has_one_hard or has_multi_mod or has_mod_goal:
        return "intermediate"

    # Beginner - everything else
    return "beginner"


# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

chatbot = ERIICA()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_chat():
    try:
        data          = request.json
        user_scenario = data.get("scenario", "")
        response      = chatbot.start(user_scenario)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data        = request.json
        chat_history = data.get("chat_history", [])
        response    = chatbot.reply(chat_history)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile", methods=["GET"])
def get_profile():
    try:
        scenario = session.get("current_scenario", "")
        raw_case = session.get("top_case_raw", "")

        if not scenario:
            # BUG FIX: log a warning so CORS/cookie issues are visible in the console.
            print("[profile] Warning: no current_scenario in session — possible CORS/cookie issue.")
            return jsonify({"profile": None})

        profile = {"scenario": scenario}
        if raw_case:
            profile.update(chatbot.parse_profile(raw_case))

        return jsonify({"profile": profile})
    except Exception as e:
        print(f"[profile] error: {e}")
        return jsonify({"profile": None})


@app.route("/api/scenarios", methods=["GET"])
def get_scenarios():
    try:
        n         = request.args.get("n", 6, type=int)
        scenarios = chatbot.get_sample_scenarios(n)
        return jsonify({"scenarios": scenarios})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    try:
        data         = request.json
        chat_history = data.get("chat_history", [])
        scenario     = data.get("scenario", session.get("current_scenario", ""))

        if len(chat_history) < 2:
            return jsonify({"error": "Conversation too short to evaluate."}), 400

        result = chatbot.evaluate(chat_history, scenario)
        if result:
            return jsonify({"evaluation": result})
        return jsonify({"error": "Evaluation failed. Please try again."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test_rag")
def test_rag():
    """Dev-only endpoint: test RAG retrieval with a query string."""
    scenario = request.args.get("q", "terminal cancer patient afraid of dying")
    context  = chatbot.retrieve_cases(scenario)
    return jsonify({"retrieved": context})


if __name__ == "__main__":
    # Render assigns a dynamic port via environment variable
    # Defaulting to 10000 ensures compatibility with Render's web servers.
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)