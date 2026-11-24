"""汇总 JSON 与中文 Markdown 巡展核对报告。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import allocate, causal, io, ledger
from .adjudicate import rates_by_dimension, support_envelope


def build_report(data_dir: str | Path = "data", asof: int = 38, ledger_path: str | Path | None = None) -> dict[str, Any]:
    packet = io.load_packet(data_dir)
    ledger_obj = ledger.Ledger(ledger_path) if ledger_path else None
    current_packet = ledger.overlay_packet(packet, ledger_obj) if ledger_obj and ledger_obj.events() else packet

    from .adjudicate import adjudicate

    completion = adjudicate(current_packet, asof=asof)
    result = {
        "data_dir": str(data_dir),
        "asof": asof,
        "completion": completion,
        "support_envelope": support_envelope(packet, asof=asof),
        "rates": {
            "city": rates_by_dimension(completion, "city"),
            "edition": rates_by_dimension(completion, "edition"),
            "opened": rates_by_dimension(completion, "opened"),
            "visit_block": rates_by_dimension(completion, "visit_block"),
        },
        "itt": causal.itt_summary(packet, asof=asof),
        "realized_benefits": causal.realized_benefits(packet, asof=asof),
        "access_classes": causal.access_evidence_classes(packet, asof=asof),
        "allocation": allocate.allocation_report(packet, asof=asof),
        "cutoff_frontiers": {
            str(cutoff): allocate.quota_frontier(packet, asof=cutoff, decision_day=cutoff)
            for cutoff in (31, 34, asof)
        },
        "commitment_dispositions": ledger.commitment_dispositions(packet, asof=asof),
    }
    if ledger_obj:
        result["ledger"] = ledger.requery(packet, ledger_obj, asof=asof)
    return result


def write_json(report: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")


def _pct(row: dict[str, Any]) -> str:
    if row["completion_rate_observed"] is None:
        return "无足窗样本"
    return f"{row['complete']}/{row['observed']} = {row['completion_rate_observed']:.0%}"


def render_markdown(report: dict[str, Any]) -> str:
    completion = report["completion"]
    lines: list[str] = []
    lines.append("# 补件试运行与新一轮分配核对\n")
    lines.append(f"资料 cutoff：第 {report['asof']} 日。未知/未取得均未按零处理。\n")
    itt = report["itt"]
    strict_zero = all(row["reliable_additional"] == 0 for row in report["allocation"]["strict_cutoff_frontier"])
    stock_two = next(row for row in report["allocation"]["stock_window_frontier"] if row["quota"] == 2)
    lines.append("## 结论摘要\n")
    lines.append(
        f"- 过去班次的足窗已知样本为 invited 0/2、ordinary 0/3；风险差点估计 {itt['known_case_risk_difference']:.0%}，"
        "资料不能证明发资格提高了齐套率。"
    )
    lines.append("- H4/H7 共 4 册因有效观测窗提前结束而保留为观察不足，未清成零。")
    lines.append(
        f"- 共享库存的资源前沿最多可可靠支持 {stock_two['reliable_additional']} 册"
        f"（其中受保护老版册 {stock_two['protected']} 册），但这要求在证据/寄送时点及早签认。"
    )
    if strict_zero:
        lines.append("- 站在第 38 日当天新寄发，按最坏寄送窗没有无条件可靠的新整组承诺；应先核 D2 签收与 D3 寄出凭证。")
    lines.append("- 以下候选在总齐套规模和受保护册数上并列，不按观察缺件率高低擅自排序。\n")

    lines.append("## 1. 齐套认定总览\n")
    lines.append("| 册 | 版本 | 地区 | 班次 | 状态 | 原因 | 已认可槽位 | 待核槽位 | 确缺槽位 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    reason_cn = {
        "full_window": "已足窗",
        "window_open": "窗口未满",
        "access_truncated": "有效访问提前结束",
        "identity_or_assignment_pending": "身份/归属待核",
    }
    status_cn = {"complete": "能确认齐套", "incomplete": "确定未齐套", "insufficient": "观察不足"}
    for a in completion["albums"]:
        accepted = ",".join(x["position"] for x in a["accepted_slots"]) or "-"
        uncertain = ",".join(a["uncertain_slots"]) or "-"
        missing = ",".join(a["missing_slots"]) or "-"
        lines.append(
            f"| {a['album']} | {a['edition']} | {a['city']} | {a['visit_block']} | "
            f"{status_cn[a['status']]} | {reason_cn.get(a['reason'], a['reason'])} | {accepted} | {uncertain} | {missing} |"
        )

    envelope = report["support_envelope"]
    lines.append(
        f"\n同一次全局认定枚举 {envelope['scenario_count']} 个归属世界：可支持齐套规模 "
        f"{envelope['min_complete_scale']}–{envelope['max_complete_scale']} 册；"
        "筛选地区/册型只过滤该全局结果，不重新放大同一张卡。"
    )
    if envelope["distinct_missing_distributions"]:
        dist_text = "；".join(
            "{" + ", ".join(f"{k}:{v}" for k, v in dist.items()) + "}"
            for dist in envelope["distinct_missing_distributions"]
        )
        lines.append(f"缺件位置分布（不同可行认定）：{dist_text}。\n")

    lines.append("\n## 2. 分层齐套率（未知不并入零）\n")
    for dimension, title in [("city", "地区"), ("edition", "册型"), ("opened", "开册日"), ("visit_block", "同批班次")]:
        lines.append(f"### 按{title}\n")
        lines.append("| 分组 | 足窗齐套率 | 确认齐套 | 确定未齐套 | 观察不足 | 总数 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in report["rates"][dimension]:
            lines.append(
                f"| {row['group']} | {_pct(row)} | {row['complete']} | {row['incomplete']} | {row['insufficient']} | {row['total']} |"
            )
        lines.append("")

    itt = report["itt"]
    lines.append("## 3. 事前分派 ITT 对照\n")
    lines.append("| 事前分派 | 班次 | 册 | 已知样本 | 齐套 | 未齐套 | 观察不足 | 已知齐套率 | 全样本界限 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for row in itt["rows"]:
        rate = "-" if row["known_rate"] is None else f"{row['known_rate']:.0%}"
        bounds = f"[{row['all_rate_bounds'][0]:.0%}, {row['all_rate_bounds'][1]:.0%}]"
        lines.append(
            f"| {row['arm']} | {','.join(row['blocks'])} | {','.join(row['albums'])} | {row['known']} | "
            f"{row['complete']} | {row['incomplete']} | {row['insufficient']} | {rate} | {bounds} |"
        )
    rd = itt["known_case_risk_difference"]
    lines.append(f"\n已知样本风险差：{rd:.0%}。" if rd is not None else "\n已知样本不足，无法计算风险差。")
    if itt["all_album_risk_difference_bounds"]:
        lo, hi = itt["all_album_risk_difference_bounds"]
        lines.append(f"把观察不足按最好/最坏处理时，风险差界限为 [{lo:.0%}, {hi:.0%}]。")
    benefits = report["realized_benefits"]
    lines.append(
        f"\n可核实的中间产出：跨册/馆交换后仍在册的槽位 {len(benefits['exchange_supported_active_slots'])} 个、"
        f"shared 槽位 {len(benefits['shared_supported_active_slots'])} 个、"
        f"寄单中已有签收记录的卡 {len(benefits['commitment_marks_with_receipt_by_cutoff'])} 张；"
        f"足窗齐套为 {benefits['full_window_complete_among_observed']}。"
    )
    if benefits["physically_complete_after_window_not_window_success"]:
        names = ",".join(item["album"] for item in benefits["physically_complete_after_window_not_window_success"])
        lines.append(f"- {names} 现在已物理齐套，但末张超过约定窗口，不能计为足窗收益。")
    lines.append("- " + benefits["caution"])
    lines.append("\n**解释边界**：")
    for item in itt["interpretation"] + itt["interference"]:
        lines.append(f"- {item}")

    lines.append("\n## 4. 客服按册凭证队列\n")
    from .adjudicate import verification_queue

    queue = verification_queue(io.load_packet(report["data_dir"]), asof=report["asof"])
    for album_id in sorted({x["album"] for x in queue}):
        items = [x for x in queue if x["album"] == album_id][:2]
        lines.append(f"- **{album_id}**：" + "；".join(x["ask_for"] for x in items))

    lines.append("\n## 5. 新一轮额度与候选分配\n")
    strict_frontier = report["allocation"]["strict_cutoff_frontier"]
    stock_frontier = report["allocation"]["stock_window_frontier"]
    cutoff_34 = report["cutoff_frontiers"]["34"]
    lines.append("### 关键历史决策点：第 34 日证据/寄送窗\n")
    for quota in (1, 2):
        row = next(item for item in cutoff_34 if item["quota"] == quota)
        lines.append(
            f"- 额度 {quota}：可靠新增 {row['reliable_additional']}，{_protected_text(row)}，"
            f"并列候选 {len(row['candidates'])} 个。"
        )
        for plan in row["candidates"][:8]:
            lines.append(_format_plan(plan))
    lines.append("\n### 以第 38 日为决策时点、按最坏寄送日窗\n")
    for row in strict_frontier:
        lines.append(
            f"- 额度 {row['quota']}：可靠新增 {row['reliable_additional']}，{_protected_text(row)}；"
            f"候选方案 {len(row['candidates'])} 个。"
        )
        for plan in row["candidates"][:3]:
            lines.append(_format_plan(plan))
    lines.append("\n### 若在库存可用/证据可判时点及早签认（候选前沿，不等于第 38 日仍可承诺）\n")
    for row in stock_frontier:
        lines.append(
            f"- 额度 {row['quota']}：最大可可靠新增 {row['reliable_additional']}，{_protected_text(row)}；"
            f"并列候选 {len(row['candidates'])} 个。"
        )
        for plan in row["candidates"][:8]:
            lines.append(_format_plan(plan))
    floor = stock_frontier[0]["floor"] if stock_frontier else None
    if floor:
        lines.append(
            f"\n来源保证口径（{floor['phase']} / cutoff {floor['cutoff']}）：至少 {floor['min_additional']} 个可靠新增、"
            f"受保护份额下限 {floor['protected_fraction']:.0%}。及早候选中的 2 册方案为 1/2=50%，满足该口径；"
            "第 38 日才决策的新寄发方案没有无条件满足者，不能把候选收益写成已承诺或已齐套。"
        )

    lines.append("\n### 请求级时点冲突\n")
    for req in report["allocation"]["request_options_now"]:
        feasible = len(req["feasible_bundles"])
        all_bundles = len(req["bundles"])
        timing = req["timing_feasible_bundles"]
        best = min(req["bundles"], key=lambda b: b["shortfall_days"], default=None)
        shortfall = f"；最早最坏到达仍晚 {best['shortfall_days']} 天" if best and best["shortfall_days"] else ""
        conditional = "；存在只待凭证/时点的候选" if timing and not feasible else ""
        lines.append(
            f"- {req['request']} / {req['album']}：确缺 {','.join(req['needed_positions']) or '无'}；"
            f"在途待签槽位 {','.join(req['in_flight_positions']) or '无'}；"
            f"当前时点可靠整组方案 {feasible}/{all_bundles}{shortfall}{conditional}。"
        )

    lines.append("\n## 6. 原寄单处置（不覆盖原单）\n")
    for item in report["commitment_dispositions"]:
        lines.append(
            f"- {item['dispatch']} → {item['album']}：{item['disposition']}；"
            f"未到手 {','.join(item['not_yet_received']) or '无'}；原单不覆盖。"
        )

    lines.append("\n## 7. 人群证据分层\n")
    for item in report["access_classes"]:
        lines.append(
            f"- {item['request']}/{item['album']}：`{item['primary_class']}`；"
            f"渠道={item['channel']}，访问标签={item['access_tag']}，证据={item['evidence_tag']}。"
        )

    return "\n".join(lines) + "\n"


def _protected_text(row: dict[str, Any]) -> str:
    if "protected_worst" not in row:
        return "受保护 0"
    if row["protected_worst"] == row["protected_best"]:
        return f"受保护老版册 {row['protected_best']}"
    return f"受保护老版册最差 {row['protected_worst']}、最好 {row['protected_best']}"


def _format_plan(plan: dict[str, Any]) -> str:
    allocations = []
    for item in plan["allocations"]:
        marks = "+".join(item["marks"])
        allocations.append(f"{item['album']}[{marks}]")
    return "  - 方案：" + "，".join(allocations) + f"；受保护 {plan['protected']}/{plan['size']}；用卡 {','.join(plan['marks'])}"
