"""共享库存、寄送窗、容量与整组缺件的可兑现分配。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import io
from .adjudicate import adjudicate, design_slot_map


def _release_dates(packet: io.Packet) -> dict[str, int]:
    released: dict[str, int] = {}
    for move in io.movements(packet):
        if move["action"] == "give_back" and move["mark"]:
            released[move["mark"]] = max(released.get(move["mark"], 0), move["received"])
    return released


def _maybe_occupied_marks(packet: io.Packet, asof: int) -> set[str]:
    """保守返回在任一证据/归属世界中可能已被册内实物占用的编号卡。"""
    from .adjudicate import active_claims, evidence_worlds

    occupied: set[str] = set()
    for world in evidence_worlds(packet, asof):
        for claim in active_claims(world["events"], asof):
            if not claim["mark"].startswith(("U", "?")):
                occupied.add(claim["mark"])
    return occupied


def reliable_stock(packet: io.Packet, asof: int = 38) -> list[dict[str, Any]]:
    card_rows = io.cards(packet)
    released = _release_dates(packet)
    maybe_occupied = _maybe_occupied_marks(packet, asof)
    sent_locked = {
        mark
        for commitment in io.commitments(packet)
        if commitment["sent"] is not None and commitment["sent"] <= asof
        for mark in commitment["marks"]
    }
    offered = {
        mark
        for commitment in io.commitments(packet)
        if commitment["state"] == "offered"
        for mark in commitment["marks"]
    }

    stock = []
    for mark, card in card_rows.items():
        free_since = max(card["available"], released.get(mark, card["available"]))
        reliable_free = mark not in maybe_occupied and mark not in sent_locked
        stock.append(
            {
                **card,
                "free_since": free_since,
                "reliable_free": reliable_free,
                "occupied_or_uncertain": mark in maybe_occupied,
                "sent_locked": mark in sent_locked,
                "existing_unsent_offer": mark in offered,
            }
        )
    return stock


def _in_flight_slots(packet: io.Packet, asof: int = 10**12) -> dict[str, set[str]]:
    slot_of = design_slot_map(io.checklist(packet))
    result: dict[str, set[str]] = defaultdict(set)
    received = {
        (m["album"], m["mark"])
        for m in io.movements(packet)
        if m["action"] == "receive" and m["received"] <= asof and m["mark"]
    }
    for commitment in io.commitments(packet):
        if commitment["sent"] is None or commitment["sent"] > asof:
            continue
        for mark in commitment["marks"]:
            if (commitment["album"], mark) not in received:
                card = io.cards(packet).get(mark)
                if card:
                    result[commitment["album"]].add(slot_of[card["design"]])
    return result


def _arrival(card: dict[str, Any], req: dict[str, Any], decision_day: int | None, lanes: dict[tuple[str, str], dict[str, int]]) -> dict[str, Any]:
    free_since = card["free_since"]
    start = free_since if decision_day is None else max(decision_day, free_since)
    if req["channel"] == "counter" and card["city"] == req["destination"]:
        return {"ship_day": start, "earliest_arrival": start, "latest_arrival": start, "lane": None}
    lane = lanes.get((card["city"], req["destination"]))
    if lane is None:
        return {"ship_day": start, "earliest_arrival": None, "latest_arrival": None, "lane": None}
    return {
        "ship_day": start,
        "earliest_arrival": start + lane["earliest"],
        "latest_arrival": start + lane["latest"],
        "lane": f"{card['city']}->{req['destination']}",
    }


def request_bundles(
    packet: io.Packet,
    asof: int = 38,
    decision_day: int | None = 38,
    include_uncertain: bool = False,
) -> list[dict[str, Any]]:
    report = adjudicate(packet, asof=asof)
    album_by_id = {a["album"]: a for a in report["albums"]}
    albums = {a["album"]: a for a in io.albums(packet)}
    permitted = io.checklist(packet)
    stock = {c["mark"]: c for c in reliable_stock(packet, asof)}
    lanes = io.delivery(packet)
    in_flight = _in_flight_slots(packet, asof)

    result = []
    for req in io.requests(packet):
        aid = req["album"]
        album = album_by_id[aid]
        missing = list(album["missing_slots"])
        if include_uncertain:
            missing.extend(album["uncertain_slots"])
        pending_slots = in_flight.get(aid, set())
        needed = [p for p in missing if p not in pending_slots]

        slot_options: list[list[dict[str, Any]]] = []
        for position in needed:
            allowed_designs = set(permitted[(album["edition"], position)])
            candidates = []
            for mark, card in stock.items():
                if not card["reliable_free"]:
                    continue
                if card["design"] not in allowed_designs:
                    continue
                if card["city"] not in req["available_city"]:
                    continue
                timing = _arrival(card, req, decision_day, lanes)
                candidates.append({"mark": mark, **card, "timing": timing})
            slot_options.append(candidates)

        evidence_pending = bool(album["uncertain_slots"]) and not include_uncertain
        bundles: list[dict[str, Any]] = []
        if needed and all(slot_options):
            for picked in _cartesian(slot_options):
                timings = [c["timing"] for c in picked]
                latest_arrival = max(t["latest_arrival"] for t in timings)
                earliest_arrival = max(t["earliest_arrival"] for t in timings)
                marks = tuple(c["mark"] for c in picked)
                parcel_lanes = tuple(sorted({t["lane"] for t in timings if t["lane"]}))
                feasible = latest_arrival <= req["latest"]
                bundles.append(
                    {
                        "marks": marks,
                        "cards": [
                            {
                                "mark": c["mark"],
                                "design": c["design"],
                                "city": c["city"],
                                "free_since": c["free_since"],
                                "timing": c["timing"],
                                "existing_unsent_offer": c["existing_unsent_offer"],
                            }
                            for c in picked
                        ],
                        "positions": tuple(needed),
                        "parcel_lanes": parcel_lanes,
                        "earliest_arrival": earliest_arrival,
                        "latest_arrival": latest_arrival,
                        "meets_deadline": feasible,
                        "evidence_pending": evidence_pending,
                        "reliable": feasible and not evidence_pending,
                        "shortfall_days": max(0, latest_arrival - req["latest"]),
                    }
                )

        result.append(
            {
                "request": req["request"],
                "album": aid,
                "edition": album["edition"],
                "city": albums[aid]["city"],
                "protected": albums[aid]["protected"],
                "channel": req["channel"],
                "deadline": req["latest"],
                "needed_positions": needed,
                "in_flight_positions": sorted(pending_slots),
                "album_status_at_cutoff": album["status"],
                "evidence_pending": evidence_pending,
                "bundles": bundles,
                "timing_feasible_bundles": [b for b in bundles if b["meets_deadline"]],
                "feasible_bundles": [b for b in bundles if b.get("reliable")],
            }
        )
    return result


def _cartesian(lists: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    result: list[list[dict[str, Any]]] = [[]]
    for options in lists:
        result = [prefix + [option] for prefix in result for option in options]
    return result


def enumerate_plans(
    packet: io.Packet,
    asof: int = 38,
    decision_day: int | None = 38,
    quota: int | None = None,
) -> list[dict[str, Any]]:
    request_options = request_bundles(packet, asof=asof, decision_day=decision_day)
    lanes = io.delivery(packet)
    all_plans: list[dict[str, Any]] = []

    def lane_ok(parcel_lanes: tuple[str, ...], counts: dict[str, int]) -> bool:
        for lane in parcel_lanes:
            # parcel_lanes are "A->B"; capacity table key uses tuple.
            from_city, to_city = lane.split("->")
            limit = lanes[(from_city, to_city)]["max_parcels"]
            if counts.get(lane, 0) + 1 > limit:
                return False
        return True

    def visit(index: int, chosen: list[dict[str, Any]], marks: set[str], lane_counts: dict[str, int]) -> None:
        if index == len(request_options):
            if chosen:
                protected = sum(1 for item in chosen if item["protected"])
                size = len(chosen)
                all_plans.append(
                    {
                        "size": size,
                        "protected": protected,
                        "protected_share": protected / size,
                        "albums": [item["album"] for item in chosen],
                        "requests": [item["request"] for item in chosen],
                        "allocations": chosen,
                        "marks": sorted(marks),
                        "lane_counts": dict(lane_counts),
                    }
                )
            return

        visit(index + 1, chosen, marks, lane_counts)
        req = request_options[index]
        if quota is not None and len(chosen) >= quota:
            return
        for bundle in req["feasible_bundles"]:
            bundle_marks = set(bundle["marks"])
            if bundle_marks & marks:
                continue
            if not lane_ok(bundle["parcel_lanes"], lane_counts):
                continue
            next_lanes = dict(lane_counts)
            for lane in bundle["parcel_lanes"]:
                next_lanes[lane] = next_lanes.get(lane, 0) + 1
            allocation = {
                "request": req["request"],
                "album": req["album"],
                "protected": req["protected"],
                "channel": req["channel"],
                "deadline": req["deadline"],
                **bundle,
            }
            visit(index + 1, chosen + [allocation], marks | bundle_marks, next_lanes)

    visit(0, [], set(), {})
    return all_plans


def quota_frontier(packet: io.Packet, asof: int = 38, decision_day: int | None = 38) -> list[dict[str, Any]]:
    guarantees = io.guarantees(packet)
    applicable = [g for g in guarantees if g["cutoff"] <= asof]
    floor_row = max(applicable or guarantees, key=lambda g: g["cutoff"])
    requests = io.requests(packet)
    max_quota = len(requests)
    frontier = []

    for quota in range(1, max_quota + 1):
        plans = enumerate_plans(packet, asof=asof, decision_day=decision_day, quota=quota)
        if not plans:
            frontier.append({"quota": quota, "reliable_additional": 0, "protected": 0, "candidates": []})
            continue
        best_size = max(p["size"] for p in plans)
        sized = [p for p in plans if p["size"] == best_size]
        best_protected = max(p["protected"] for p in sized)
        worst_protected = min(p["protected"] for p in sized)
        # 同一可靠齐套规模下，不替业务在不同受保护份额/缺件分布间强行排序；
        # 全部候选保留，并给出最差受保护份额。
        frontier.append(
            {
                "quota": quota,
                "reliable_additional": best_size,
                "protected": best_protected,
                "protected_best": best_protected,
                "protected_worst": worst_protected,
                "protected_share": best_protected / best_size,
                "worst_protected_share": worst_protected / best_size,
                "protected_request_cell_total": sum(
                    1 for r in requests if next(a for a in io.albums(packet) if a["album"] == r["album"])["protected"]
                ),
                "floor": floor_row,
                "meets_min_additional": best_size >= floor_row["min_additional"],
                "meets_protected_fraction": worst_protected / best_size >= floor_row["protected_fraction"],
                "candidates": sized,
            }
        )
    return frontier


def allocation_report(packet: io.Packet, asof: int = 38) -> dict[str, Any]:
    return {
        "asof": asof,
        "strict_cutoff_frontier": quota_frontier(packet, asof=asof, decision_day=asof),
        "stock_window_frontier": quota_frontier(packet, asof=asof, decision_day=None),
        "request_options_now": request_bundles(packet, asof=asof, decision_day=asof),
        "request_options_from_stock_date": request_bundles(packet, asof=asof, decision_day=None),
        "stock": reliable_stock(packet, asof=asof),
    }
