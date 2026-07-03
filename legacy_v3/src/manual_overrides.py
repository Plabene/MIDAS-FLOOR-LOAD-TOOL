from pathlib import Path

import yaml


def load_manual_overrides(path):
    path = Path(path)
    if not path.exists():
        return {"include_floor_load_groups": set(), "exclude_floor_load_groups": set()}
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    overrides = data.get("manual_overrides", data)
    return {
        "include_floor_load_groups": set(overrides.get("include_floor_load_groups") or []),
        "exclude_floor_load_groups": set(overrides.get("exclude_floor_load_groups") or []),
    }


def apply_manual_overrides(rows, overrides):
    include = overrides.get("include_floor_load_groups", set())
    exclude = overrides.get("exclude_floor_load_groups", set())
    for row in rows:
        group_key = row.get("floor_load_group_key")
        row.setdefault("manual_override", False)
        row.setdefault("manual_override_action", "")
        row.setdefault("manual_override_reason", "")
        if group_key in include:
            row["manual_override"] = True
            row["manual_override_action"] = "include"
            row["manual_override_reason"] = "config/manual_overrides.yml include_floor_load_groups"
            row["exclude_from_mgtx"] = False
            row["exclusion_reason"] = ""
            row["review_flag"] = True
        elif group_key in exclude:
            row["manual_override"] = True
            row["manual_override_action"] = "exclude"
            row["manual_override_reason"] = "config/manual_overrides.yml exclude_floor_load_groups"
            row["exclude_from_mgtx"] = True
            row["exclusion_reason"] = "manual override exclude"
    return rows
