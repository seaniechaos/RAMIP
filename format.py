"""format: render the morning brief as plain text for delivery."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CLUSTERS_PATH = ROOT / "clustered_items.json"
FETCHED_PATH = ROOT / "fetched_items.json"
OUTPUT_PATH = ROOT / "brief.txt"

CET = ZoneInfo("Europe/Paris")
MAX_ITEMS_PER_CLUSTER = 5

FOOTER = (
    "Current primary beats: Iran | Hormuz | Oil | Fed/Treasury | "
    "Gold | Critical Minerals | Private Credit"
)

logger = logging.getLogger("ramip.format")


def _top_beat(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "QUIET DAY"
    label = (clusters[0].get("label") or "").strip()
    return label.split(" — ", 1)[0] if label else "QUIET DAY"


def _scanned_count() -> int | None:
    if not FETCHED_PATH.exists():
        return None
    try:
        return len(json.loads(FETCHED_PATH.read_text()))
    except (OSError, json.JSONDecodeError):
        return None


def _format_cluster(cluster: dict[str, Any]) -> str:
    lines = [cluster.get("label") or "UNCATEGORIZED"]
    synthesis = (cluster.get("synthesis") or "").strip()
    if synthesis:
        lines.append(synthesis)
    lines.append("")
    for item in (cluster.get("items") or [])[:MAX_ITEMS_PER_CLUSTER]:
        title = (item.get("title") or "").strip() or "(untitled)"
        source = (item.get("source") or "").strip() or "?"
        link = (item.get("link") or "").strip()
        lines.append(f"  • {title} ({source})")
        if link:
            lines.append(f"    {link}")
    return "\n".join(lines)


def format_brief() -> tuple[str, int, int]:
    """Render brief.txt and return (text, n_clusters, n_surfaced)."""
    if CLUSTERS_PATH.exists():
        clusters: list[dict[str, Any]] = json.loads(CLUSTERS_PATH.read_text())
    else:
        logger.warning("no %s — run cluster first", CLUSTERS_PATH.name)
        clusters = []

    now = datetime.now(timezone.utc).astimezone(CET)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M %Z")

    surfaced = sum(len(c.get("items") or []) for c in clusters)
    scanned = _scanned_count()
    scanned_str = str(scanned) if scanned is not None else "?"

    subject_line = (
        f"Subject: RAMIP Brief — {date_str} — {_top_beat(clusters)} "
        f"({len(clusters)} clusters)"
    )

    header_lines = [
        f"Date: {date_str}",
        f"Time generated (CET): {time_str}",
        f"Total items scanned: {scanned_str}",
        f"Items surfaced: {surfaced}",
        f"Clusters formed: {len(clusters)}",
    ]

    parts = [subject_line, "", *header_lines, ""]
    if clusters:
        for cluster in clusters:
            parts.append(_format_cluster(cluster))
            parts.append("")
    else:
        parts.append("(no clusters today)")
        parts.append("")
    parts.append("---")
    parts.append(FOOTER)

    text = "\n".join(parts).rstrip() + "\n"
    OUTPUT_PATH.write_text(text)
    logger.info("wrote brief to %s", OUTPUT_PATH)
    return text, len(clusters), surfaced


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    _, n_clusters, n_surfaced = format_brief()
    print(
        f"brief written to {OUTPUT_PATH.name}: "
        f"{n_clusters} clusters, {n_surfaced} items"
    )


if __name__ == "__main__":
    main()
