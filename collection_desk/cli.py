"""命令行入口：生成报告、查册、重查和追加客服事件。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import io, ledger
from .adjudicate import verification_queue
from .report import build_report, write_json, render_markdown


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deskctl", description=__doc__)
    parser.add_argument("--data", default="data", type=Path)
    parser.add_argument("--asof", default=38, type=int)
    parser.add_argument("--ledger", default=".desk-state/events.jsonl", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("report", help="生成 JSON 和 Markdown 汇总")
    album_parser = sub.add_parser("album", help="查看单册认定与待核凭证")
    album_parser.add_argument("album")
    sub.add_parser("itt", help="事前分派 ITT 对照")
    sub.add_parser("plan", help="库存分配前沿")
    sub.add_parser("queue", help="客服凭证队列")
    sub.add_parser("dispositions", help="原寄单处置建议")

    receive = sub.add_parser("receive", help="追加交卡/签收记录后重查")
    receive.add_argument("--album", required=True)
    receive.add_argument("--mark", required=True)
    receive.add_argument("--day", required=True, type=int)
    receive.add_argument("--design")

    exchange = sub.add_parser("exchange", help="追加跨册/馆换件记录后重查")
    exchange.add_argument("--from", dest="from_album", required=True)
    exchange.add_argument("--to", dest="to_album", required=True)
    exchange.add_argument("--mark", required=True)
    exchange.add_argument("--day", required=True, type=int)
    exchange.add_argument("--design")

    signoff = sub.add_parser("signoff", help="登记客服签认")
    signoff.add_argument("--album", required=True)
    signoff.add_argument("--by", required=True)
    signoff.add_argument("--dispatch")
    signoff.add_argument("--plan-json")

    sent = sub.add_parser("mark-sent", help="补录实际寄出日")
    sent.add_argument("--dispatch", required=True)
    sent.add_argument("--day", required=True, type=int)
    sent.add_argument("--marks", nargs="*")

    redirect = sub.add_parser("redirect", help="登记改寄确认")
    redirect.add_argument("--dispatch", required=True)
    redirect.add_argument("--destination", required=True)
    redirect.add_argument("--day", required=True, type=int)
    redirect.add_argument("--note", default="")

    trace = sub.add_parser("trace", help="追踪承诺依据和后续齐套")
    trace.add_argument("--dispatch", required=True)

    args = parser.parse_args(argv)
    packet = io.load_packet(args.data)
    book = ledger.Ledger(args.ledger)

    if args.command == "report":
        report = build_report(args.data, asof=args.asof, ledger_path=args.ledger)
        out_json = Path("reports/result.json")
        out_md = Path("reports/analysis.md")
        write_json(report, out_json)
        out_md.parent.mkdir(exist_ok=True)
        out_md.write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {out_json} and {out_md}")
        return 0

    if args.command == "album":
        result = ledger.requery(packet, book, asof=args.asof)
        album = next((a for a in result["albums"] if a["album"] == args.album), None)
        if album is None:
            raise SystemExit(f"找不到册 {args.album}")
        album["verification_queue"] = [x for x in verification_queue(packet, args.asof, args.album)][:2]
        _print(album)
    elif args.command == "itt":
        from .causal import itt_summary

        _print(itt_summary(packet, args.asof))
    elif args.command == "plan":
        from .allocate import allocation_report

        _print(allocation_report(packet, args.asof))
    elif args.command == "queue":
        _print(verification_queue(packet, args.asof))
    elif args.command == "dispositions":
        _print(ledger.commitment_dispositions(packet, args.asof))
    elif args.command == "receive":
        event = book.card_received(args.album, args.mark, args.day, args.design)
        result = ledger.requery(packet, book, asof=max(args.asof, args.day))
        album = next(a for a in result["albums"] if a["album"] == args.album)
        _print({"event": event, "album": album})
    elif args.command == "exchange":
        event = book.exchange(args.from_album, args.to_album, args.mark, args.day, args.design)
        result = ledger.requery(packet, book, asof=max(args.asof, args.day))
        albums = [a for a in result["albums"] if a["album"] in {args.from_album, args.to_album}]
        _print({"event": event, "albums": albums})
    elif args.command == "signoff":
        plan = json.loads(args.plan_json) if args.plan_json else None
        event = book.signoff(args.album, args.by, plan, args.dispatch)
        _print(event)
    elif args.command == "mark-sent":
        event = book.dispatch_sent(args.dispatch, args.day, args.marks or [])
        _print(event)
    elif args.command == "redirect":
        event = book.redirect_confirmed(args.dispatch, args.destination, args.day, args.note)
        _print(event)
    elif args.command == "trace":
        _print(ledger.trace(packet, book, args.dispatch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
