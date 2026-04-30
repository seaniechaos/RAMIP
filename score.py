"""score: rank fetched items against beat definitions via the Claude API."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "fetched_items.json"
OUTPUT_PATH = ROOT / "scored_items.json"

# claude-sonnet-4-20250514 (the spec's dated ID) is deprecated and retires
# 2026-06-15. claude-sonnet-4-6 is the current Sonnet alias.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 300
SCORE_THRESHOLD = 6

SYSTEM_PROMPT = """\
You are an editorial relevance scorer for a financial and geopolitical newsletter called Rude Awakening, written by Sean Ring.
Sean's primary beats are: Iran conflict, Strait of Hormuz, Oil markets, U.S. foreign policy, Fed and Treasury macro, Precious metals, Critical minerals, Private credit stress.
Sean's analytical frameworks: selectorate theory (who controls the winning coalition), Cantillon Effect (who benefits from money printing), contrarian lens (what is consensus missing).
Score each story from 0-10 for relevance to Sean's beats. Return ONLY a JSON object — no preamble, no markdown — with this exact schema:
{"score": 7, "beats": ["Iran", "Oil Markets"], "so_what": "One plain-English sentence framing why this matters to Sean."}"""

logger = logging.getLogger("ramip.score")


def _format_user_message(item: dict[str, Any]) -> str:
    summary = (item.get("summary") or "")[:500]
    return (
        f"Title: {item.get('title', '')} | "
        f"Summary: {summary} | "
        f"Source: {item.get('source', '')} | "
        f"Published: {item.get('published', '')}"
    )


def _parse_score(text: str) -> dict[str, Any] | None:
    """Parse the model's JSON reply, falling back to extracting the first {...} block."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _score_one(
    client: anthropic.Anthropic, item: dict[str, Any]
) -> dict[str, Any] | None:
    """Score a single item. Returns a merged dict, or None on error/refusal/parse failure."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _format_user_message(item)}],
        )
    except anthropic.APIStatusError as exc:
        logger.error("API error scoring %r: %s", item.get("link"), exc)
        return None

    if response.stop_reason == "refusal":
        logger.warning("model refused to score %r", item.get("link"))
        return None

    text = next((b.text for b in response.content if b.type == "text"), "")
    parsed = _parse_score(text)
    if not parsed or "score" not in parsed:
        logger.warning("unparseable response for %r: %r", item.get("link"), text[:200])
        return None

    return {**item, **parsed}


def score_all() -> tuple[list[dict[str, Any]], int]:
    if not INPUT_PATH.exists():
        logger.warning("no %s — run fetch first", INPUT_PATH.name)
        OUTPUT_PATH.write_text("[]")
        return [], 0

    items = json.loads(INPUT_PATH.read_text())
    if not items:
        OUTPUT_PATH.write_text("[]")
        return [], 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set (check .env)")

    # SDK auto-retries 429 + 5xx with exponential backoff; bump the cap from default 2.
    client = anthropic.Anthropic(api_key=api_key, max_retries=5)

    above_threshold: list[dict[str, Any]] = []
    total_scored = 0
    for item in items:
        result = _score_one(client, item)
        if result is None:
            continue
        total_scored += 1
        if result.get("score", 0) >= SCORE_THRESHOLD:
            above_threshold.append(result)

    OUTPUT_PATH.write_text(json.dumps(above_threshold, indent=2, ensure_ascii=False))
    logger.info("wrote %d items to %s", len(above_threshold), OUTPUT_PATH)
    return above_threshold, total_scored


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()
    above, total_scored = score_all()
    print(f"{total_scored} items scored, {len(above)} items above threshold")


if __name__ == "__main__":
    main()
