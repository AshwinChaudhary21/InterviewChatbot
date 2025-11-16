# mongo.py
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import traceback

from pymongo import MongoClient, errors
from pymongo.collection import Collection
from bson import ObjectId


DEFAULT_DB_NAME = "interview"
DEFAULT_COLLECTION = "candidates"


# -----------------------
# Low-level DB client
# -----------------------
class MongoDB:
    def __init__(self, uri: Optional[str] = None, db_name: str = DEFAULT_DB_NAME):
        self._uri = uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self._db_name = db_name
        self._client: Optional[MongoClient] = None
        self._db = None
        self._candidates: Optional[Collection] = None
        self.connect()

    def connect(self) -> None:
        if self._client:
            return
        try:
            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
            # Force connection to verify credentials/availability
            self._client.server_info()
            self._db = self._client[self._db_name]
            self._candidates = self._db[DEFAULT_COLLECTION]
            self._ensure_indexes()
        except errors.ServerSelectionTimeoutError as ex:
            raise ConnectionError(f"Could not connect to MongoDB: {ex}")

    def _ensure_indexes(self) -> None:
        try:
            # ensure email unique for candidate upserts
            self._candidates.create_index("email", unique=True)
        except Exception:
            # index creation should not break app startup; log to stdout
            print("Warning: index creation issue (maybe duplicates exist).")

    def insert_candidate(self, candidate: Dict[str, Any]) -> ObjectId:
        doc = dict(candidate)
        doc.setdefault("created_at", datetime.utcnow())
        # normalize answer timestamps if present
        answers = doc.get("answers", [])
        for a in answers:
            a.setdefault("timestamp", datetime.utcnow())
        doc["answers"] = answers
        try:
            res = self._candidates.insert_one(doc)
            return res.inserted_id
        except errors.DuplicateKeyError:
            raise ValueError("Candidate with this email already exists.")

    def upsert_candidate(self, email: str, profile: Dict[str, Any]) -> None:
        p = dict(profile)
        p.pop("answers", None)
        p["updated_at"] = datetime.utcnow()
        self._candidates.update_one(
            {"email": email},
            {"$set": p, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )

    def add_answer(self, email: str, answer: Dict[str, Any], upsert_candidate_if_missing: bool = True) -> None:
        a = dict(answer)
        a.setdefault("timestamp", datetime.utcnow())
        self._candidates.update_one(
            {"email": email},
            {"$push": {"answers": a}, "$set": {"updated_at": datetime.utcnow()}},
            upsert=bool(upsert_candidate_if_missing),
        )

    def get_candidate_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self._candidates.find_one({"email": email})

    def list_candidates(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._candidates.find().sort("created_at", -1).limit(limit))

    def get_candidate_with_last_n_answers(self, email: str, n: int = 5) -> Optional[Dict[str, Any]]:
        return self._candidates.find_one({"email": email}, {"answers": {"$slice": -n}, "name": 1, "email": 1, "phone": 1, "position": 1, "meta": 1, "created_at": 1})

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._candidates = None


# -----------------------
# Singleton accessor
# -----------------------
_db_instance: Optional[MongoDB] = None


def get_db(uri: Optional[str] = None, db_name: str = DEFAULT_DB_NAME) -> MongoDB:
    """
    Return a singleton MongoDB instance. Safe to call multiple times.
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = MongoDB(uri=uri, db_name=db_name)
    return _db_instance


# -----------------------
# High-level app API
# -----------------------

# module-level wrapper instance (initialised by init_mongo or auto-init)
_db_wrapper: Optional[MongoDB] = None


def init_mongo(uri: Optional[str] = None, db_name: Optional[str] = None) -> None:
    """
    Initialize the DB wrapper used by app code. Safe to call multiple times.
    If no arguments provided it will use environment variable MONGO_URI or default to localhost.
    """
    global _db_wrapper
    if _db_wrapper is not None:
        return
    try:
        _db_wrapper = get_db(uri, db_name or DEFAULT_DB_NAME)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize MongoDB: {e}")


def _normalize_answer_input(ans: Dict[str, Any]) -> Dict[str, Any]:
    a = dict(ans or {})
    a.setdefault("question_id", a.get("question_id") or a.get("qid") or None)
    a.setdefault("question", a.get("question") or a.get("q") or "")
    a.setdefault("answer", a.get("answer") or a.get("response") or "")
    a.setdefault("tech", a.get("tech") or "General")
    a.setdefault("score", a.get("score", None))
    a.setdefault("timestamp", a.get("timestamp") or datetime.utcnow())
    return a


def save_candidate_and_answers(candidate: Dict[str, Any], answers_list: List[Dict[str, Any]]) -> str:
    """
    Upsert candidate by email and push answers to the candidate.answers array.
    Returns the candidate _id as string.
    Raises RuntimeError on failure.
    """
    global _db_wrapper
    if _db_wrapper is None:
        # try auto-init (uses MONGO_URI env or localhost)
        try:
            init_mongo()
        except Exception as e:
            raise ConnectionError(f"MongoDB not initialized and auto-init failed: {e}")

    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a dict")

    email = (candidate.get("email") or candidate.get("Email") or candidate.get("email_address") or "").strip()
    if not email:
        raise ValueError("Candidate must include an 'email' field to save to MongoDB.")

    # Build a conservative profile (won't overwrite answers)
    profile = {
        "name": candidate.get("name", candidate.get("full_name", "")).strip(),
        "email": email,
        "phone": candidate.get("phone", candidate.get("phone_number", "")).strip(),
        "position": candidate.get("position", candidate.get("desired_position", "")),
        "meta": candidate.get("meta", {"status": "in_progress"}),
        "tech_stack": candidate.get("tech_stack", []),
    }

    try:
        # upsert profile
        _db_wrapper.upsert_candidate(email=email, profile=profile)

        # push answers
        for raw in answers_list or []:
            norm = _normalize_answer_input(raw)
            ans_doc = {
                "question_id": norm.get("question_id"),
                "question": norm.get("question"),
                "answer": norm.get("answer"),
                "tech": norm.get("tech"),
                "score": norm.get("score"),
                "timestamp": norm.get("timestamp"),
            }
            _db_wrapper.add_answer(email, ans_doc)

        # return _id
        doc = _db_wrapper.get_candidate_by_email(email)
        if not doc:
            raise RuntimeError("Failed to retrieve candidate after save.")
        cid = doc.get("_id")
        return str(cid) if isinstance(cid, ObjectId) else str(cid)
    except Exception as ex:
        tb = traceback.format_exc()
        raise RuntimeError(f"Failed to save candidate and answers: {ex}\n\n{tb}")
