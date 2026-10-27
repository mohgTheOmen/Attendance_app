"""Text extraction engines. Each takes image bytes and returns candidate name lines."""
import base64
import json
import os
import shutil
from functools import lru_cache

import httpx

from app.config import get_settings
from app.ocr.preprocess import prepare

WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class EngineUnavailable(RuntimeError):
    pass


@lru_cache
def tesseract_cmd() -> str | None:
    configured = get_settings().tesseract_cmd
    if configured:
        return configured
    return shutil.which("tesseract") or (WINDOWS_TESSERACT if os.path.exists(WINDOWS_TESSERACT) else None)


def tesseract_lines(data: bytes) -> list[str]:
    import pytesseract

    cmd = tesseract_cmd()
    if not cmd:
        raise EngineUnavailable("Tesseract is not installed (set TESSERACT_CMD)")
    pytesseract.pytesseract.tesseract_cmd = cmd
    # psm 4: a single column of text of variable sizes, i.e. a handwritten list
    text = pytesseract.image_to_string(prepare(data), lang=get_settings().ocr_lang, config="--psm 4")
    return [line.strip() for line in text.splitlines() if line.strip()]


AZURE_PROMPT = (
    "This is a photo of a handwritten or printed attendance list. Transcribe every person's name, "
    "one entry per person, in the order written. Copy the spelling as written (keep diacritics). "
    "Leave out titles, dates, session labels, grades, numbering, group codes and notes like 'Erasmus'. "
    'Reply with JSON only: {"names": ["...", "..."]}'
)


def azure_configured() -> bool:
    s = get_settings()
    return bool(s.azure_openai_endpoint and s.azure_openai_api_key and s.azure_openai_deployment)


def azure_lines(data: bytes) -> list[str]:
    """Azure OpenAI chat completions with image input (any vision-capable deployment)."""
    s = get_settings()
    if not azure_configured():
        raise EngineUnavailable("Azure OpenAI is not configured (AZURE_OPENAI_ENDPOINT / _API_KEY / _DEPLOYMENT)")
    url = (f"{s.azure_openai_endpoint.rstrip('/')}/openai/deployments/{s.azure_openai_deployment}"
           f"/chat/completions?api-version={s.azure_openai_api_version}")
    image = base64.b64encode(data).decode()
    body = {
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": AZURE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"}},
        ]}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    try:
        r = httpx.post(url, json=body, headers={"api-key": s.azure_openai_api_key}, timeout=90)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        names = json.loads(content).get("names", [])
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise EngineUnavailable(f"Azure OpenAI request failed: {exc}") from exc
    return [str(n).strip() for n in names if str(n).strip()]


ENGINES = {"tesseract": tesseract_lines, "azure": azure_lines}


def available_engines() -> dict[str, bool]:
    return {"tesseract": tesseract_cmd() is not None, "azure": azure_configured()}
