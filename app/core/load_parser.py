from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LoadLayerInfo:
    layer: str
    real_name: str
    dl: float
    ll: float
    source: str = "layer"

    @property
    def floor_load_type_name(self) -> str:
        return self.real_name.strip() or self.layer


def parse_load_layer(text: str) -> LoadLayerInfo:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("레이어명이 비어 있습니다.")
    normalized = raw.replace("，", ",")
    normalized = re.sub(r"[\[\](){}]", " ", normalized)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    dl_match = re.search(r"\bDL\s*[:=]?\s*(-?\d+(?:\.\d+)?)", normalized, flags=re.IGNORECASE)
    ll_match = re.search(r"\bLL\s*[:=]?\s*(-?\d+(?:\.\d+)?)", normalized, flags=re.IGNORECASE)
    if not dl_match and not ll_match:
        raise ValueError("레이어명에서 DL/LL 값을 읽을 수 없습니다. 예: 사무실, DL:1.2 LL:3.0")
    dl = float(dl_match.group(1)) if dl_match else 0.0
    ll = float(ll_match.group(1)) if ll_match else 0.0

    name_part = raw
    name_part = re.sub(r"LOAD[_\s-]*\d+[_\s-]*", "", name_part, flags=re.IGNORECASE)
    name_part = re.sub(r"DL\s*[:=_]?\s*-?\d+(?:\.\d+)?", "", name_part, flags=re.IGNORECASE)
    name_part = re.sub(r"LL\s*[:=_]?\s*-?\d+(?:\.\d+)?", "", name_part, flags=re.IGNORECASE)
    name_part = name_part.replace("_", " ").replace(",", " ")
    name_part = re.sub(r"\s+", " ", name_part).strip(" -_.,")
    if not name_part:
        name_part = raw
    return LoadLayerInfo(layer=raw, real_name=name_part, dl=dl, ll=ll)


def make_safe_load_layer_name(index: int, real_name: str, dl: float, ll: float, *, max_len: int = 240) -> str:
    name = re.sub(r"[<>:\"/\\|?*\n\r\t,;=]", "_", str(real_name or "LOAD").strip())
    name = re.sub(r"\s+", "_", name).strip("_") or "LOAD"
    layer = f"LOAD_{index:03d}_{name}_DL_{_fmt(dl)}_LL_{_fmt(ll)}"
    return layer[:max_len].rstrip("_")


def _fmt(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"
