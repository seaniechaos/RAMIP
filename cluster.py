"""cluster: group scored items into beat-aligned clusters with synthesis."""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "scored_items.json"
OUTPUT_PATH = ROOT / "clustered_items.json"

# claude-sonnet-4-20250514 (the spec's dated ID) is deprecated and retires
# 2026-06-15. claude-sonnet-4-6 is the current Sonnet alias.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 150
TIME_WINDOW = timedelta(hours=24)
SHARED_BEATS_THRESHOLD = 2

SYNTHESIS_SYSTEM_PROMPT = """\
You are Sean Ring, author of the Rude Awakening newsletter. Write ONE contrarian, sardonic sentence that synthesises the cluster of related stories below into a single editorial take.
Lean on Sean's frameworks where they fit: selectorate theory (who controls the winning coalition), the Cantillon Effect (who benefits from money printing), and a contrarian lens (what is consensus missing).
Return ONLY the sentence — no preamble, no quotes, no markdown."""

logger = logging.getLogger("ramip.cluster")


def _parse_date(s: str | None) -> datetime | None:
    """Parse RSS/Atom date strings; return None on failure."""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _build_clusters(items: list[dict[str, Any]]) -> list[list[int]]:
    """Return a list of clusters, each a list of indices into `items`."""
    n = len(items)
    uf = _UnionFind(n)
    dates = [_parse_date(it.get("published")) for it in items]
    beat_sets = [set(it.get("beats") or []) for it in items]

    for i in range(n):
        for j in range(i + 1, n):
            if dates[i] is None or dates[j] is None:
                continue
            if abs(dates[i] - dates[j]) > TIME_WINDOW:
                continue
            if len(beat_sets[i] & beat_sets[j]) >= SHARED_BEATS_THRESHOLD:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


def _label_for(items: list[dict[str, Any]]) -> str:
    counts: Counter[str] = Counter()
    for it in items:
        for beat in it.get("beats") or []:
            counts[beat] += 1
    if not counts:
        return "UNCATEGORIZED"
    top = [beat for beat, _ in counts.most_common(2)]
    return " — ".join(beat.upper() for beat in top)


def _synthesise(
    client: anthropic.Anthropic, label: str, items: list[dict[str, Any]]
) -> str:
    bullets = "\n".join(
        f"- {it.get('title', '')}: {it.get('so_what', '')}" for it in items
    )
    user = f"Cluster: {label}\n\nStories:\n{bullets}"
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as exc:
        logger.error("API error synthesising %s: %s", label, exc)
        return ""
    if response.stop_reason == "refusal":
        logger.warning("model refused to synthesise %s", label)
        return ""
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text.strip().strip('"').strip("'")


def cluster_all() -> tuple[list[dict[str, Any]], int]:
    if not INPUT_PATH.exists():
        logger.warning("no %s — run score first", INPUT_PATH.name)
        OUTPUT_PATH.write_text("[]")
        return [], 0

    items = json.loads(INPUT_PATH.read_text())
    if not items:
        OUTPUT_PATH.write_text("[]")
        return [], 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set (check .env)")
    client = anthropic.Anthropic(api_key=api_key, max_retries=5)

    clusters: list[dict[str, Any]] = []
    for indices in _build_clusters(items):
        cluster_items = sorted(
            (items[i] for i in indices),
            key=lambda it: it.get("score", 0),
            reverse=True,
        )
        scores = [it.get("score", 0) for it in cluster_items]
        avg = sum(scores) / len(scores) if scores else 0
        label = _label_for(cluster_items)
        synthesis = _synthesise(client, label, cluster_items)
        trimmed = [
            {
                "title": it.get("title", ""),
                "link": it.get("link", ""),
                "source": it.get("source", ""),
                "score": it.get("score", 0),
                "so_what": it.get("so_what", ""),
            }
            for it in cluster_items
        ]
        clusters.append(
            {
                "label": label,
                "synthesis": synthesis,
                "items": trimmed,
                "_avg_score": avg,
            }
        )

    clusters.sort(key=lambda c: c["_avg_score"], reverse=True)
    for c in clusters:
        c.pop("_avg_score", None)

    OUTPUT_PATH.write_text(json.dumps(clusters, indent=2, ensure_ascii=False))
    logger.info("wrote %d clusters to %s", len(clusters), OUTPUT_PATH)
    return clusters, len(items)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()
    clusters, total = cluster_all()
    print(f"{len(clusters)} clusters formed from {total} items")


if __name__ == "__main__":
    main()
