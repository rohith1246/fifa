import json
import logging
import os
import time
from typing import Any, Dict, List, Tuple
import google.generativeai as genai
import requests
from sqlalchemy.orm import joinedload
from models import StadiumGate

logger = logging.getLogger(__name__)

# In-memory gate telemetry cache (30-second TTL) to reduce redundant DB reads
_gate_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}


def get_cached_gate_dicts(db: Any) -> List[Dict[str, Any]]:
    """
    Returns cached stadium gate data as serialized dictionaries.
    Caches for 30 seconds to reduce redundant DB reads during high traffic.
    Stores plain dicts (not ORM objects) to prevent SQLAlchemy detached-instance errors
    after the originating session is closed.
    Args:
        db: Active SQLAlchemy database session.
    Returns:
        List[Dict[str, Any]]: Ordered list of gate data dictionaries.
    """
    now = time.time()
    if _gate_cache["data"] is not None and now < _gate_cache["expires_at"]:
        return _gate_cache["data"]  # type: ignore[return-value]
    gates = (
        db.query(StadiumGate)
        .options(joinedload(StadiumGate.allocations))
        .order_by(StadiumGate.name)
        .all()
    )
    # Serialize to dicts immediately so the cache is session-independent
    gate_dicts: List[Dict[str, Any]] = [g.to_dict() for g in gates]
    _gate_cache["data"] = gate_dicts
    _gate_cache["expires_at"] = now + 30.0
    return gate_dicts


def invalidate_gate_cache() -> None:
    """Clears the in-memory gate cache to force a fresh DB read on next request."""
    _gate_cache["data"] = None
    _gate_cache["expires_at"] = 0.0


def run_ai_generation(prompt: str, response_type: str = "text") -> Tuple[str, str]:
    """
    Orchestrates primary Google Gemini API with fallback REST support to Groq.
    Args:
        prompt (str): Text prompt to submit to the AI model.
        response_type (str): Output format specification (text or json).
    Returns:
        Tuple[str, str]: Generated output text and model provider used ("gemini" or "groq").
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    # Primary: Gemini API
    if gemini_key and gemini_key != "your_gemini_api_key_here":
        genai.configure(api_key=gemini_key)
        models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash-latest"]
        for m in models:
            try:
                logger.info(f"Attempting Gemini generation ({m})...")
                model = genai.GenerativeModel(m)
                config = {}
                if response_type == "json":
                    config["response_mime_type"] = "application/json"
                response = model.generate_content(prompt, generation_config=config)
                if response.text:
                    logger.info(f"Gemini {m} succeeded.")
                    return response.text.strip(), "gemini"
            except Exception as e:
                logger.warning(f"Gemini {m} generation failed: {e}")

    # Fallback: Groq REST API (direct REST request to avoid proxy configs)
    if groq_key and groq_key != "your_groq_api_key_here":
        try:
            logger.info("Gemini failed or missing API Key. Shifting to Groq REST fallback...")
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "llama-3.3-70b-specdec",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
            if response_type == "json":
                payload["response_format"] = {"type": "json_object"}

            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20,
            )
            if res.status_code == 200:
                result = res.json()["choices"][0]["message"]["content"].strip()
                logger.info("Groq API fallback succeeded.")
                return result, "groq"
            else:
                logger.error(f"Groq API returned HTTP {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Groq API connection failure: {e}")

    # Offline/Mock Fallback
    logger.warning("No operational AI API keys found. Returning mock template response.")
    if response_type == "json":
        return (
            json.dumps(
                {
                    "is_valid": True,
                    "severity": "Medium",
                    "dispatch_notes": "Alert field coordinators. Secure area and investigate immediately.",
                    "message": "Proceed carefully. Safe routes are highlighted.",
                }
            ),
            "offline_mock",
        )
    return (
        "Operations standard procedure: please deploy on-field staff to "
        "inspect the reported gate quadrant immediately.",
        "offline_mock",
    )
