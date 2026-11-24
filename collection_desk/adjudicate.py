"""齐套认定、证据候选与同一次认定中的实物排他约束。"""
from __future__ import annotations

import json
from itertools import product
from typing import Any

from . import io


def window_end(album: dict[str, Any]) -> int:
    # opened 当日为第 0 天；第 horizon 个自然日为约定截止日。
    return int(album["opened"]) + int(album["horizon"])


def design_slot_map(permitted: dict[tuple[str, str], tuple[str, ...]]) -> dict[str, str]:
    return {design: position for (_, position), designs in permitted.items() for design in designs}


def observation_state(album: dict[str, Any], design_row: dict[str, Any], asof: int) -> dict[str, Any]:
    end = window_end(album)
    until = int(design_row["until"])
    if until < end:
        return {
            "state": "insufficient",
            "reason": "access_truncated",
            "window_end": end,
            "evidence_until": until,
        }
    if asof < end:
        return {
            "state": "insufficient",
            "reason": "window_open",
            "window_end": end,
            "evidence_until": until,
        }
    return {"state": "observed", "reason": "full_window", "window_end": end, "evidence_until": until}


def _cutoff(asof: int | None) -> int:
    return 10**12 if asof is None else asof


def evidence_worlds(packet: io.Packet, asof: int | None = None) -> list[dict[str, Any]]:
    """返回未编号卡身份候选的笛卡尔世界。

    已确认候选会排除旧的 possible 候选；确认行的 received 可以覆盖旧扫描日期。
    """
    cutoff = _cutoff(asof)
    moves = io.movements(packet)
    poss = io.possibilities(packet)
    slot_of = design_slot_map(io.checklist(packet))
    unknown_choices: list[list[list[dict[str, Any]]]] = []
    unknown_moves = [m for m in moves if m["mark"] is None]

    options_by_record: dict[str, list[dict[str, Any]]] = {}
    for move in unknown_moves:
        rows = poss.get(move["record"], [])
        confirmed = [r for r in rows if r["status"] == "confirmed" and r["received"] <= cutoff]
        source = confirmed if confirmed else [r for r in rows if r["status"] == "possible" and r["received"] <= cutoff]
        if not source:
            # 没有可见候选时仍保留原始扫描，但身份和到手日均待核。
            source = [{"candidate": "?", "received": move["received"], "status": "unverified"}]
        options = [
            {
                "record": move["record"],
                "mark": row["candidate"],
                "design": move["design"],
                "action": move["action"],
                "album": move["album"],
                "received": row["received"],
                "via": move["via"],
                "identity_status": row["status"],
                "slot": slot_of.get(move["design"]),
            }
            for row in source
        ]
        options_by_record[move["record"]] = options
        unknown_choices.append(options)

    explicit_events = []
    for move in moves:
        if move["mark"] is None or move["received"] > cutoff:
            continue
        explicit_events.append({**move, "identity_status": "numbered", "slot": slot_of.get(move["design"])})

    worlds = []
    if not unknown_choices:
        choices: list[tuple[dict[str, Any], ...]] = [()]
    else:
        choices = product(*unknown_choices)  # type: ignore[assignment]
    for choice in choices:
        events = explicit_events + [dict(option) for option in choice if option["received"] <= cutoff]
        worlds.append({"choices": list(choice), "events": events})
    return worlds


def active_claims(events: list[dict[str, Any]], cutoff: int) -> list[dict[str, Any]]:
    """计算 cutoff 时点仍登记在某册上的实物主张。"""
    active: dict[tuple[str, str], dict[str, Any]] = {}
    ordered = sorted(
        (event for event in events if event["received"] <= cutoff),
        key=lambda e: (e["received"], 0 if e["action"] == "give_back" else 1, e["record"]),
    )
    for event in ordered:
        key = (event["album"], event["mark"])
        if event["action"] == "receive":
            active[key] = dict(event)
        elif event["action"] == "give_back":
            active.pop(key, None)
    return list(active.values())


def determinations(claims: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """对同一编号实物的多个归属主张做排他枚举。"""
    by_mark: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        by_mark.setdefault(claim["mark"], []).append(claim)

    unique = [rows[0] for rows in by_mark.values() if len(rows) == 1]
    contested = [rows for rows in by_mark.values() if len(rows) > 1]
    if not contested:
        return [unique]

    results = []
    for picked in product(*[range(len(rows)) for rows in contested]):
        selected = list(unique)
        for rows, index in zip(contested, picked):
            selected.append(rows[index])
        results.append(selected)
    return results


def _covered(claims: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    covered: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in claims:
        if claim.get("slot"):
            covered.setdefault((claim["album"], claim["slot"]), []).append(claim)
    return covered


def adjudicate(packet: io.Packet, asof: int = 38) -> dict[str, Any]:
    album_rows = io.albums(packet)
    design_rows = io.designs(packet)
    required = {(row["edition"], row["position"]): io.values(row["permitted"]) for row in packet.table("checklist")}
    positions_by_edition: dict[str, list[str]] = {}
    for edition, position in required:
        positions_by_edition.setdefault(edition, []).append(str(position))

    worlds = evidence_worlds(packet, asof)
    album_results: dict[str, dict[str, Any]] = {}
    global_scales: list[int] = []

    for album in album_rows:
        album_id = album["album"]
        design_row = design_rows[album["visit_block"]]
        observation = observation_state(album, design_row, asof)
        positions = sorted(positions_by_edition[album["edition"]])
        album_results[album_id] = {
            "album": album_id,
            "edition": album["edition"],
            "city": album["city"],
            "opened": album["opened"],
            "visit_block": album["visit_block"],
            "wave": design_row["wave"],
            "assigned": design_row["assigned"],
            "protected": album["protected"],
            "window_end": observation["window_end"],
            "observation": observation["state"],
            "reason": observation["reason"],
            "positions": positions,
            "slot_evidence": {
                position: {"covered_in_all": True, "covered_in_any": False, "claims": []}
                for position in positions
            },
            "complete_in_any_determination": False,
        }

    # 每个证据世界内，按各册窗口截止日截取主张，再全局枚举实物归属。
    for world in worlds:
        window_claims: list[dict[str, Any]] = []
        for album in album_rows:
            end = window_end(album)
            window_cutoff = min(asof, end)
            album_claims = [
                claim
                for claim in active_claims(world["events"], window_cutoff)
                if claim["album"] == album["album"]
            ]
            window_claims.extend(album_claims)

        for selected in determinations(window_claims):
            covered = _covered(selected)
            complete_ids = set()
            for album in album_rows:
                aid = album["album"]
                positions = sorted(positions_by_edition[album["edition"]])
                is_complete = all((aid, position) in covered for position in positions)
                if is_complete:
                    complete_ids.add(aid)
                result = album_results[aid]
                result["complete_in_any_determination"] |= is_complete
                for position in positions:
                    key = (aid, position)
                    info = result["slot_evidence"][position]
                    if key in covered:
                        info["covered_in_any"] = True
                        claim_summaries = [
                            {
                                "mark": c["mark"],
                                "design": c["design"],
                                "record": c["record"],
                                "received": c["received"],
                                "status": c.get("identity_status"),
                            }
                            for c in covered[key]
                        ]
                        for claim in claim_summaries:
                            if claim not in info["claims"]:
                                info["claims"].append(claim)
                    else:
                        info["covered_in_all"] = False
            global_scales.append(len(complete_ids))

    albums_out = []
    for album in album_rows:
        aid = album["album"]
        result = album_results[aid]
        accepted: list[dict[str, Any]] = []
        possible: list[str] = []
        missing: list[str] = []
        for position in result["positions"]:
            info = result["slot_evidence"][position]
            item = {
                "position": position,
                "covered_in_all": info["covered_in_all"],
                "covered_in_any": info["covered_in_any"],
                "claims": info["claims"],
            }
            if info["covered_in_all"]:
                accepted.append(item)
            elif info["covered_in_any"]:
                possible.append(position)
            else:
                missing.append(position)
        result["accepted_slots"] = accepted
        result["uncertain_slots"] = possible
        result["missing_slots"] = missing

        if not missing and not possible:
            result["status"] = "complete"
        elif result["complete_in_any_determination"] or possible:
            result["status"] = "insufficient"
            result["reason"] = "identity_or_assignment_pending"
        elif result["observation"] == "observed":
            result["status"] = "incomplete"
        else:
            result["status"] = "insufficient"
        result.pop("slot_evidence", None)
        albums_out.append(result)

    # 当前时点的在手版本（包括超过足窗截止日的迟到卡），供客服核对。
    on_hand = _current_on_hand(packet, asof, worlds)
    by_album = {row["album"]: row for row in albums_out}
    for aid, items in on_hand.items():
        if aid in by_album:
            by_album[aid]["on_hand_at_cutoff"] = items

    return {
        "asof": asof,
        "albums": albums_out,
        "max_joint_complete_scale": max(global_scales, default=0),
        "min_joint_complete_scale": min(global_scales, default=0),
        "world_count": len(worlds),
    }


def _current_on_hand(packet: io.Packet, asof: int, worlds: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    # asof=38 时候选已确认，世界唯一；若仍有多个世界，列出各候选而不替客服拍板。
    result: dict[str, list[dict[str, Any]]] = {}
    for world in worlds:
        for claim in active_claims(world["events"], asof):
            result.setdefault(claim["album"], [])
            item = {
                "mark": claim["mark"],
                "design": claim["design"],
                "position": claim.get("slot"),
                "record": claim["record"],
                "received": claim["received"],
                "identity_status": claim.get("identity_status"),
            }
            if item not in result[claim["album"]]:
                result[claim["album"]].append(item)
    return result


def verification_queue(packet: io.Packet, asof: int = 38, album_id: str | None = None) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    moves = {m["record"]: m for m in io.movements(packet)}
    possibilities = io.possibilities(packet)

    for record, rows in possibilities.items():
        move = moves[record]
        if album_id and move["album"] != album_id:
            continue
        confirmed = [r for r in rows if r["status"] == "confirmed" and r["received"] <= asof]
        if not confirmed:
            visible = [r for r in rows if r["received"] <= asof]
            queue.append(
                {
                    "album": move["album"],
                    "kind": "unnumbered_scan",
                    "record": record,
                    "priority": 1,
                    "ask_for": f"核对 {record} 的交卡凭证/序号或补录单",
                    "candidates": [r["candidate"] for r in visible],
                }
            )

    received_marks = {
        (m["album"], mark)
        for m in io.movements(packet)
        if m["action"] == "receive" and m["received"] <= asof
        for mark in ([m["mark"]] if m["mark"] else [])
    }
    for commitment in io.commitments(packet):
        if album_id and commitment["album"] != album_id:
            continue
        for mark in commitment["marks"]:
            if (commitment["album"], mark) in received_marks:
                continue
            if commitment["state"] == "sent" and commitment["sent"] is not None and commitment["sent"] <= asof:
                queue.append(
                    {
                        "album": commitment["album"],
                        "kind": "signed_receipt",
                        "dispatch": commitment["dispatch"],
                        "mark": mark,
                        "priority": 1,
                        "ask_for": f"核对寄单 {commitment['dispatch']} 中 {mark} 的签收/改寄凭证",
                        "promised": commitment["promised"],
                    }
                )
        pending_marks = [mark for mark in commitment["marks"] if (commitment["album"], mark) not in received_marks]
        if commitment["state"] == "offered" and commitment["sent"] is None and pending_marks:
            queue.append(
                {
                    "album": commitment["album"],
                    "kind": "dispatch_or_signoff",
                    "dispatch": commitment["dispatch"],
                    "marks": pending_marks,
                    "priority": 2,
                    "ask_for": f"补录 {commitment['dispatch']}（{','.join(pending_marks)}）是否经客服签认并实际寄出",
                    "promised": commitment["promised"],
                }
            )

    queue.sort(key=lambda x: (x["album"], x["priority"], x.get("record", ""), x.get("dispatch", "")))
    return queue


def support_envelope(packet: io.Packet, asof: int = 38) -> dict[str, Any]:
    """枚举同一证据/归属认定下的齐套规模与缺件分布。"""
    album_rows = io.albums(packet)
    positions_by_edition: dict[str, list[str]] = {}
    for row in packet.table("checklist"):
        positions_by_edition.setdefault(row["edition"], []).append(row["position"])

    scenarios = []
    for world in evidence_worlds(packet, asof):
        claims_by_album: dict[str, list[dict[str, Any]]] = {}
        for album in album_rows:
            cutoff = min(asof, window_end(album))
            claims_by_album[album["album"]] = [
                claim for claim in active_claims(world["events"], cutoff) if claim["album"] == album["album"]
            ]
        merged = [claim for claims in claims_by_album.values() for claim in claims]
        for selected in determinations(merged):
            covered = _covered(selected)
            missing_by_position: dict[str, int] = {}
            complete_albums: list[str] = []
            missing_albums: dict[str, list[str]] = {}
            for album in album_rows:
                aid = album["album"]
                missing = [
                    position
                    for position in sorted(positions_by_edition[album["edition"]])
                    if (aid, position) not in covered
                ]
                missing_albums[aid] = missing
                if not missing:
                    complete_albums.append(aid)
                for position in missing:
                    missing_by_position[position] = missing_by_position.get(position, 0) + 1
            scenarios.append(
                {
                    "complete_scale": len(complete_albums),
                    "complete_albums": complete_albums,
                    "missing_by_position": dict(sorted(missing_by_position.items())),
                    "missing_albums": missing_albums,
                }
            )

    scales = [item["complete_scale"] for item in scenarios]
    distributions = {
        json.dumps(item["missing_by_position"], ensure_ascii=False, sort_keys=True)
        for item in scenarios
    }
    return {
        "scenario_count": len(scenarios),
        "min_complete_scale": min(scales, default=0),
        "max_complete_scale": max(scales, default=0),
        "distinct_missing_distributions": [json.loads(item) for item in sorted(distributions)],
        "scenarios": scenarios,
    }


def rates_by_dimension(report: dict[str, Any], key: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, int]] = {}
    for album in report["albums"]:
        dimension = album[key]
        group = groups.setdefault(dimension, {"group": str(dimension), "complete": 0, "incomplete": 0, "insufficient": 0, "total": 0})
        group[album["status"]] += 1
        group["total"] += 1
    for group in groups.values():
        observed = group["complete"] + group["incomplete"]
        group["observed"] = observed
        group["completion_rate_observed"] = group["complete"] / observed if observed else None
    return sorted(groups.values(), key=lambda g: g["group"])
