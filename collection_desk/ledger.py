"""追加式客服/巡展事件账。

原始 TSV 永不被这些操作覆盖；新事实写入 JSONL，重查时生成叠加视图。
已寄出的卡通过 sent_locked 保留，不会重新进入可派库存。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import io
from .adjudicate import adjudicate, design_slot_map


@dataclass(frozen=True)
class LedgerEvent:
    seq: int
    type: str
    at: str
    payload: dict[str, Any]


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        rows = self.events()
        event = {"seq": len(rows) + 1, "type": event_type, "at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        with self.path.open("a", encoding="utf-8") as source:
            source.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def signoff(self, album: str, by: str, plan: dict[str, Any] | None = None, dispatch: str | None = None) -> dict[str, Any]:
        return self.append("customer_signoff", album=album, by=by, plan=plan or {}, dispatch=dispatch)

    def card_received(self, album: str, mark: str, day: int, design: str | None = None, record: str | None = None) -> dict[str, Any]:
        return self.append("card_received", album=album, mark=mark, day=day, design=design, record=record)

    def exchange(self, from_album: str, to_album: str, mark: str, day: int, design: str | None = None) -> dict[str, Any]:
        return self.append(
            "exchange_confirmed",
            from_album=from_album,
            to_album=to_album,
            mark=mark,
            day=day,
            design=design,
        )

    def redirect_confirmed(self, dispatch: str, new_destination: str, effective_day: int, note: str = "") -> dict[str, Any]:
        return self.append(
            "redirect_confirmed",
            dispatch=dispatch,
            new_destination=new_destination,
            effective_day=effective_day,
            note=note,
        )

    def dispatch_sent(self, dispatch: str, sent_day: int, marks: list[str] | None = None) -> dict[str, Any]:
        return self.append("dispatch_sent", dispatch=dispatch, sent_day=sent_day, marks=marks or [])


def overlay_packet(packet: io.Packet, ledger: Ledger | list[dict[str, Any]]) -> io.Packet:
    """把账本事件叠加到资料副本；不修改磁盘输入。"""
    events = ledger.events() if isinstance(ledger, Ledger) else ledger
    tables = {name: [dict(row) for row in rows] for name, rows in packet.tables.items()}
    movement_fields = packet.layout["movements.tsv"]
    next_n = len(tables["movements.tsv"]) + 1

    sent_updates: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event["type"]
        payload = event["payload"]
        if event_type == "card_received":
            mark = payload["mark"]
            card = io.cards(packet).get(mark)
            design = payload.get("design") or (card["design"] if card else "?")
            record = payload.get("record") or f"L{next_n}"
            next_n += 1
            row = {
                "record": record,
                "album": payload["album"],
                "mark": mark,
                "design": design,
                "action": "receive",
                "day": str(payload["day"]),
                "received": str(payload["day"]),
                "via": "ledger_receipt",
            }
            tables["movements.tsv"].append({key: row.get(key, "?") for key in movement_fields})
        elif event_type == "exchange_confirmed":
            mark = payload["mark"]
            card = io.cards(packet).get(mark)
            design = payload.get("design") or (card["design"] if card else "?")
            base_record = f"L{next_n}"
            next_n += 1
            common = {"mark": mark, "design": design, "day": str(payload["day"]), "received": str(payload["day"]), "via": "ledger_exchange"}
            for suffix, album, action in (
                ("G", payload["from_album"], "give_back"),
                ("R", payload["to_album"], "receive"),
            ):
                row = {"record": f"{base_record}{suffix}", "album": album, "action": action, **common}
                tables["movements.tsv"].append({key: row.get(key, "?") for key in movement_fields})
        elif event_type == "dispatch_sent":
            sent_updates.setdefault(payload["dispatch"], {}).update(payload)
        elif event_type == "redirect_confirmed":
            update = sent_updates.setdefault(payload["dispatch"], {})
            update["redirect"] = payload

    commitment_fields = packet.layout["commitments.tsv"]
    updated_commitments = []
    for row in tables["commitments.tsv"]:
        row = dict(row)
        update = sent_updates.get(row["dispatch"])
        if update and "sent_day" in update:
            row["sent"] = str(update["sent_day"])
            row["state"] = "sent"
        if update and "redirect" in update:
            row["redirect"] = update["redirect"]["new_destination"]
        updated_commitments.append({key: row.get(key, "?") for key in commitment_fields})
    tables["commitments.tsv"] = updated_commitments

    dispatch_album = {row["dispatch"]: row["album"] for row in io.commitments(packet)}
    redirected_albums = {
        dispatch_album[dispatch]: update["redirect"]["new_destination"]
        for dispatch, update in sent_updates.items()
        if "redirect" in update and dispatch in dispatch_album
    }
    if redirected_albums:
        request_fields = packet.layout["requests.tsv"]
        updated_requests = []
        for row in tables["requests.tsv"]:
            row = dict(row)
            if row["album"] in redirected_albums:
                row["destination"] = redirected_albums[row["album"]]
            updated_requests.append({key: row.get(key, "?") for key in request_fields})
        tables["requests.tsv"] = updated_requests

    return io.Packet(root=packet.root, layout=packet.layout, tables=tables)


def requery(packet: io.Packet, ledger: Ledger | list[dict[str, Any]], asof: int = 38) -> dict[str, Any]:
    overlaid = overlay_packet(packet, ledger)
    result = adjudicate(overlaid, asof=asof)
    result["ledger_events"] = ledger.events() if isinstance(ledger, Ledger) else ledger
    return result


def commitment_dispositions(packet: io.Packet, asof: int = 38) -> list[dict[str, Any]]:
    """检查原寄单；不覆盖原单，只给待换/待补和可用卡。"""
    from .allocate import reliable_stock

    report = adjudicate(packet, asof=asof)
    album_by_id = {a["album"]: a for a in report["albums"]}
    cards = io.cards(packet)
    slot_of = design_slot_map(io.checklist(packet))
    stock = {c["mark"]: c for c in reliable_stock(packet, asof)}
    received = {
        (m["album"], m["mark"])
        for m in io.movements(packet)
        if m["action"] == "receive" and m["received"] <= asof and m["mark"]
    }
    result = []
    for commitment in io.commitments(packet):
        aid = commitment["album"]
        missing = album_by_id[aid]["missing_slots"]
        pending_marks = [mark for mark in commitment["marks"] if (aid, mark) not in received]
        locked_marks = list(commitment["marks"]) if commitment["sent"] is not None else []
        replacement_options = []
        for position in missing:
            permitted = set(io.checklist(packet).get((album_by_id[aid]["edition"], position), ()))
            options = [
                {"mark": mark, "design": card["design"], "city": card["city"], "free_since": card["free_since"]}
                for mark, card in stock.items()
                if card["reliable_free"] and card["design"] in permitted
            ]
            replacement_options.append({"position": position, "options": options})
        pending_slots = {slot_of.get(cards[mark]["design"]) for mark in pending_marks if mark in cards}
        can_complete = not missing or set(missing).issubset(pending_slots)
        result.append(
            {
                "dispatch": commitment["dispatch"],
                "album": aid,
                "original_marks": list(commitment["marks"]),
                "state": commitment["state"],
                "sent": commitment["sent"],
                "promised": commitment["promised"],
                "not_yet_received": pending_marks,
                "sent_marks_locked": locked_marks,
                "current_missing_slots": missing,
                "pending_covers_slots": sorted(slot for slot in pending_slots if slot),
                "can_still_complete_if_pending_arrives": can_complete,
                "disposition": _disposition_name(commitment, pending_marks, asof),
                "replacement_or_supplement_options": replacement_options,
                "do_not_overwrite": True,
            }
        )
    return result


def _disposition_name(commitment: dict[str, Any], pending_marks: list[str], asof: int) -> str:
    if not pending_marks:
        return "received_check_completion"
    if commitment["state"] == "offered" and commitment["sent"] is None:
        return "await_signoff_or_dispatch_proof"
    if commitment["promised"] is not None and commitment["promised"] < asof:
        return "overdue_trace_then_replace_or_supplement"
    return "await_receipt_no_reinventory"


def trace(packet: io.Packet, ledger: Ledger, dispatch: str) -> dict[str, Any]:
    events = [e for e in ledger.events() if e["payload"].get("dispatch") == dispatch]
    later = requery(packet, ledger, asof=10**9)
    album = None
    dispatch_row = next((c for c in io.commitments(packet) if c["dispatch"] == dispatch), None)
    if dispatch_row:
        album = next((a for a in later["albums"] if a["album"] == dispatch_row["album"]), None)
    return {"dispatch": dispatch, "events": events, "later_album_status": album}
