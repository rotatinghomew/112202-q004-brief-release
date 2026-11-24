"""事前分派的 ITT 描述与小样本界限。

资料没有册级抽签结果，只有 visit_block 的事前分派字段和 0.5 的设计概率。
因此这里只能做班次层面的 ITT 对照；chance 不能被当成某一册的实际处理状态。
"""
from __future__ import annotations

from typing import Any

from . import io
from .adjudicate import adjudicate


def itt_summary(packet: io.Packet, asof: int = 38) -> dict[str, Any]:
    report = adjudicate(packet, asof=asof)
    designs = io.designs(packet)
    groups: dict[str, dict[str, Any]] = {}

    for album in report["albums"]:
        design = designs[album["visit_block"]]
        if design["wave"] != "past":
            continue
        arm = design["assigned"]
        group = groups.setdefault(
            arm,
            {"arm": arm, "complete": 0, "incomplete": 0, "insufficient": 0, "albums": [], "blocks": set()},
        )
        group[album["status"]] += 1
        group["albums"].append(album["album"])
        group["blocks"].add(album["visit_block"])

    rows = []
    for arm, group in sorted(groups.items()):
        known = group["complete"] + group["incomplete"]
        total = group["complete"] + group["incomplete"] + group["insufficient"]
        rows.append(
            {
                "arm": arm,
                "blocks": sorted(group["blocks"]),
                "albums": group["albums"],
                "total": total,
                "known": known,
                "complete": group["complete"],
                "incomplete": group["incomplete"],
                "insufficient": group["insufficient"],
                "known_rate": group["complete"] / known if known else None,
                # 未知组最坏/最好都齐套时的界限；不得把未知清成 0。
                "all_rate_bounds": [group["complete"] / total, (group["complete"] + group["insufficient"]) / total],
            }
        )

    invited = next((r for r in rows if r["arm"] == "invited"), None)
    ordinary = next((r for r in rows if r["arm"] == "ordinary"), None)
    contrast = None
    bounds = None
    if invited and ordinary and invited["known_rate"] is not None and ordinary["known_rate"] is not None:
        contrast = invited["known_rate"] - ordinary["known_rate"]
        bounds = [
            invited["all_rate_bounds"][0] - ordinary["all_rate_bounds"][1],
            invited["all_rate_bounds"][1] - ordinary["all_rate_bounds"][0],
        ]

    return {
        "unit": "album joined to pre-assigned visit_block arm",
        "rows": rows,
        "known_case_risk_difference": contrast,
        "all_album_risk_difference_bounds": bounds,
        "chance": 0.5,
        "interpretation": [
            "按 design.assigned 做事前分派（ITT），不按 movements.via、寄单或后来是否补齐回溯分组。",
            "H4 的 until=15 早于 A5/A7 的足窗截止日，列为观察不足，不能当作完整对照组零完成。",
            "已知足窗样本中两组齐套数均为 0；点估计不支持‘已观察到提升’，但样本极小且存在干扰，不能证明无效果。",
        ],
        "interference": [
            "共同赠卡/shared 库存使同一批卡可能替代另一来访者的需求。",
            "C2、C6、C19 均有跨册/馆交换链；处理组放出或带回的卡会改变另一组结果。",
            "同一实物在一次全局认定中最多给一册，不能在城市或册型筛选时重复计为两份证据。",
        ],
    }


def realized_benefits(packet: io.Packet, asof: int = 38) -> dict[str, Any]:
    """区分活动量、槽位改善与可证实的足窗齐套。"""
    from .adjudicate import active_claims, evidence_worlds, window_end

    report = adjudicate(packet, asof=asof)
    album_by_id = {a["album"]: a for a in report["albums"]}
    exchange_slots: list[dict[str, Any]] = []
    shared_slots: list[dict[str, Any]] = []
    for world in evidence_worlds(packet, asof):
        for claim in active_claims(world["events"], asof):
            item = {"album": claim["album"], "mark": claim["mark"], "design": claim["design"], "slot": claim.get("slot")}
            if claim.get("via") == "exchange" and item not in exchange_slots:
                exchange_slots.append(item)
            if claim.get("via") == "shared" and item not in shared_slots:
                shared_slots.append(item)

    received = {
        (m["album"], mark)
        for m in io.movements(packet)
        if m["action"] == "receive" and m["received"] <= asof
        for mark in ([m["mark"]] if m["mark"] else [])
    }
    received_commitment_marks = []
    pending_commitment_marks = []
    for commitment in io.commitments(packet):
        for mark in commitment["marks"]:
            target = received_commitment_marks if (commitment["album"], mark) in received else pending_commitment_marks
            target.append({"dispatch": commitment["dispatch"], "album": commitment["album"], "mark": mark})

    late_completions = []
    for album in io.albums(packet):
        verdict = album_by_id[album["album"]]
        end = window_end(album)
        on_hand = verdict.get("on_hand_at_cutoff", [])
        on_hand_positions = {item.get("position") for item in on_hand}
        if verdict["status"] == "incomplete" and set(verdict["positions"]).issubset(on_hand_positions):
            late_completions.append({"album": album["album"], "window_end": end, "on_hand": on_hand})

    return {
        "full_window_complete_among_observed": sum(1 for a in report["albums"] if a["status"] == "complete"),
        "exchange_supported_active_slots": exchange_slots,
        "shared_supported_active_slots": shared_slots,
        "commitment_marks_with_receipt_by_cutoff": received_commitment_marks,
        "commitment_marks_pending_receipt_or_dispatch": pending_commitment_marks,
        "physically_complete_after_window_not_window_success": late_completions,
        "caution": "领用量、寄单量和槽位覆盖都不是新增齐套数；跨册/馆同一实物不得重复计数。",
    }


def access_evidence_classes(packet: io.Packet, asof: int = 38) -> list[dict[str, Any]]:
    """把请求按接触渠道和是否有过去同地区/册型证据打标。

    资料没有个人预约、到馆能力或外部选择的完整字段，所以 mail 只标为
    “可能由寄件创造机会”，不直接断言此人正常情况下不能到馆。
    """
    report = adjudicate(packet, asof=asof)
    from .allocate import request_bundles

    bundle_view = {row["album"]: row for row in request_bundles(packet, asof=asof, decision_day=None)}
    album_by_id = {a["album"]: a for a in report["albums"]}
    albums = io.albums(packet)
    past_cell: dict[tuple[str, str], dict[str, int]] = {}
    for album in albums:
        if album_by_id[album["album"]]["wave"] != "past":
            continue
        key = (album["city"], album["edition"])
        status = album_by_id[album["album"]]["status"]
        cell = past_cell.setdefault(key, {"observed": 0, "complete": 0, "insufficient": 0})
        if status == "insufficient":
            cell["insufficient"] += 1
        else:
            cell["observed"] += 1
            if status == "complete":
                cell["complete"] += 1

    result = []
    for req in io.requests(packet):
        album = next(a for a in albums if a["album"] == req["album"])
        cell = past_cell.get((album["city"], album["edition"]), {"observed": 0, "complete": 0, "insufficient": 0})
        comparable = cell["observed"] > 0
        bundle_row = bundle_view.get(req["album"])
        timing_bundles = bundle_row["timing_feasible_bundles"] if bundle_row else []
        cross_city_required = bool(timing_bundles) and all(
            any(card["city"] != req["destination"] for card in bundle["cards"]) for bundle in timing_bundles
        )
        local_bundle_exists = any(
            all(card["city"] == req["destination"] for card in bundle["cards"]) for bundle in timing_bundles
        )

        if req["channel"] == "counter":
            access = "normal_venue_counter"
        elif cross_city_required:
            access = "arranged_cross_city_access_required"
        elif local_bundle_exists or req["destination"] in req["available_city"]:
            access = "same_city_mail_or_venue_access_unrecorded"
        else:
            access = "access_opportunity_unrecorded"

        if not comparable:
            primary = "no_comparable_past_evidence"
        elif req["channel"] == "counter":
            primary = "normal_venue_counter"
        elif cross_city_required:
            primary = "only_arranged_cross_city_opportunity_in_data"
        else:
            primary = "same_city_but_normal_visit_not_evidenced"

        result.append(
            {
                "request": req["request"],
                "album": req["album"],
                "city": album["city"],
                "edition": album["edition"],
                "protected": album["protected"],
                "channel": req["channel"],
                "access_tag": access,
                "cross_city_required": cross_city_required,
                "local_bundle_exists": local_bundle_exists,
                "evidence_tag": "comparable" if comparable else "no_valid_past_cell",
                "primary_class": primary,
                "past_cell": cell,
                "warning": "缺少个人到馆备选/预约字段时，不得把 mail 直接等同于‘只有补件带来机会’。",
            }
        )
    return result
