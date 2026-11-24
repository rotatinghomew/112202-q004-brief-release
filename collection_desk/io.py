"""离线资料读取与形状校验。

这里不把 ``?`` / ``-`` 静默转换成 0：它们分别表示未取得和不适用，
业务层必须显式处理。
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def opt_int(value: str) -> int | None:
    value = value.strip()
    if value in {"?", "-", ""}:
        return None
    return int(value)


def plain(value: str) -> str | None:
    value = value.strip()
    return None if value in {"?", "-"} else value


def values(value: str) -> tuple[str, ...]:
    value = value.strip()
    if value in {"?", "-", ""}:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def yes_no(value: str) -> bool:
    value = value.strip().lower()
    if value == "yes":
        return True
    if value == "no":
        return False
    raise ValueError(f"无法识别的是否值: {value!r}")


@dataclass(frozen=True)
class Packet:
    root: Path
    layout: dict[str, list[str]]
    tables: dict[str, list[dict[str, str]]]

    def table(self, name: str) -> list[dict[str, str]]:
        filename = name if name.endswith(".tsv") else f"{name}.tsv"
        return self.tables[filename]


def load_packet(folder: str | Path) -> Packet:
    root = Path(folder)
    with (root / "layout.json").open(encoding="utf-8") as source:
        layout: dict[str, list[str]] = json.load(source)

    tables: dict[str, list[dict[str, str]]] = {}
    for filename, fields in layout.items():
        path = root / filename
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source, delimiter="\t", strict=True)
            if reader.fieldnames != fields:
                raise ValueError(f"{filename}: 表头不符")
            rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{filename}:{line_number}: 列数不符")
                if any(not str(value).strip() for value in row.values()):
                    raise ValueError(f"{filename}:{line_number}: 有未标记的空值")
                rows.append(dict(row))
            tables[filename] = rows

    tsv_names = {path.name for path in root.glob("*.tsv")}
    if set(layout) != tsv_names:
        missing = tsv_names - set(layout)
        extra = set(layout) - tsv_names
        raise ValueError(f"layout 与 TSV 不一致；未登记={sorted(missing)}，多余={sorted(extra)}")
    return Packet(root=root, layout=layout, tables=tables)


def albums(packet: Packet) -> list[dict[str, Any]]:
    result = []
    for row in packet.table("albums"):
        result.append(
            {
                "album": row["album"],
                "edition": row["edition"],
                "city": row["city"],
                "opened": int(row["opened"]),
                "visit_block": row["visit_block"],
                "horizon": int(row["horizon"]),
                "protected": yes_no(row["protected"]),
            }
        )
    return result


def designs(packet: Packet) -> dict[str, dict[str, Any]]:
    result = {}
    for row in packet.table("design"):
        item = {
            "visit_block": row["visit_block"],
            "wave": row["wave"],
            "assigned": row["assigned"],
            "chance": float(row["chance"]),
            "visited": yes_no(row["visited"]),
            "until": int(row["until"]),
            "city": row["city"],
        }
        result[item["visit_block"]] = item
    return result


def checklist(packet: Packet) -> dict[tuple[str, str], tuple[str, ...]]:
    result = {}
    for row in packet.table("checklist"):
        result[(row["edition"], row["position"])] = values(row["permitted"])
    return result


def cards(packet: Packet) -> dict[str, dict[str, Any]]:
    result = {}
    for row in packet.table("cards"):
        result[row["mark"]] = {
            "mark": row["mark"],
            "design": row["design"],
            "minted": int(row["minted"]),
            "available": int(row["available"]),
            "city": row["city"],
        }
    return result


def movements(packet: Packet) -> list[dict[str, Any]]:
    result = []
    for row in packet.table("movements"):
        result.append(
            {
                "record": row["record"],
                "album": row["album"],
                "mark": plain(row["mark"]),
                "design": row["design"],
                "action": row["action"],
                "day": int(row["day"]),
                "received": int(row["received"]),
                "via": row["via"],
            }
        )
    return result


def possibilities(packet: Packet) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in packet.table("possibilities"):
        result.setdefault(row["record"], []).append(
            {
                "record": row["record"],
                "candidate": row["candidate"],
                "received": int(row["received"]),
                "status": row["status"],
            }
        )
    return result


def requests(packet: Packet) -> list[dict[str, Any]]:
    result = []
    for row in packet.table("requests"):
        result.append(
            {
                "request": row["request"],
                "album": row["album"],
                "channel": row["channel"],
                "latest": int(row["latest"]),
                "available_city": values(row["available_city"]),
                "destination": row["destination"],
            }
        )
    return result


def delivery(packet: Packet) -> dict[tuple[str, str], dict[str, int]]:
    result = {}
    for row in packet.table("delivery"):
        result[(row["from"], row["to"])] = {
            "earliest": int(row["earliest"]),
            "latest": int(row["latest"]),
            "max_parcels": int(row["max_parcels"]),
        }
    return result


def commitments(packet: Packet) -> list[dict[str, Any]]:
    result = []
    for row in packet.table("commitments"):
        result.append(
            {
                "dispatch": row["dispatch"],
                "album": row["album"],
                "marks": values(row["marks"]),
                "sent": opt_int(row["sent"]),
                "promised": opt_int(row["promised"]),
                "state": row["state"],
            }
        )
    return result


def guarantees(packet: Packet) -> list[dict[str, Any]]:
    result = []
    for row in packet.table("guarantees"):
        result.append(
            {
                "phase": row["phase"],
                "min_additional": int(row["min_additional"]),
                "protected_fraction": float(row["protected_fraction"]),
                "cutoff": int(row["cutoff"]),
            }
        )
    return result
