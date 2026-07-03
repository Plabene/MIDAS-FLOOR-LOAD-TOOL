from __future__ import annotations

from collections.abc import Iterable


def apply_load_display_names(items: Iterable[dict]) -> list[dict]:
    selected = [dict(item) for item in items]
    name_counts: dict[str, int] = {}
    for item in selected:
        name = str(item.get("name") or "")
        name_counts[name] = name_counts.get(name, 0) + 1

    source_name_seen: dict[tuple[str, str], int] = {}
    result: list[dict] = []
    for item in selected:
        name = str(item.get("name") or "")
        source = str(item.get("source") or "")
        display_name = name
        if name_counts.get(name, 0) > 1:
            display_name = f"{name} - {source}"
        source_name_key = (source, name)
        source_name_seen[source_name_key] = source_name_seen.get(source_name_key, 0) + 1
        if source_name_seen[source_name_key] > 1:
            display_name = f"{display_name} #{source_name_seen[source_name_key]}"
        item["display_name"] = display_name
        result.append(item)
    return result
