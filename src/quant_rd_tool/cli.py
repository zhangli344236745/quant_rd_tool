import argparse
import os

import uvicorn

from quant_rd_tool.config import settings
from quant_rd_tool.market_data import DataProvider


def main() -> None:
    p = argparse.ArgumentParser(prog="quant-rd")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run FastAPI + uvicorn")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument(
        "--reload",
        action="store_true",
        help="代码变更时自动重载（开发用）",
    )

    bt = sub.add_parser("backtest", help="akshare + qlib momentum backtest with advice")
    bt.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="A-share codes, e.g. 600519 000858",
    )
    bt.add_argument("--start", default="2023-01-01")
    bt.add_argument("--end", default=None)
    bt.add_argument("--lookback", type=int, default=20)
    bt.add_argument("--topk", type=int, default=3)
    bt.add_argument(
        "--signal",
        choices=["momentum", "ml"],
        default="momentum",
        help="momentum factor or qlib ML predictions",
    )
    bt.add_argument(
        "--ml-algo",
        choices=["xgb", "lgb", "both"],
        default="lgb",
        help="ML model when --signal ml (both uses lgb for backtest)",
    )
    bt.add_argument(
        "--provider",
        choices=["auto", "akshare", "openbb"],
        default=None,
        help="行情源：auto=akshare 优先，失败回退 OpenBB",
    )

    an = sub.add_parser("analyze", help="Single-stock: fetch, qlib dump, analysis report")
    an.add_argument("--code", required=True, help="A-share code, e.g. 600519")
    an.add_argument("--start", default="2020-01-01")
    an.add_argument("--end", default=None)
    an.add_argument("--data-dir", default="data/stocks")
    an.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download even if local CSV exists",
    )
    an.add_argument(
        "--provider",
        choices=["auto", "akshare", "openbb"],
        default=None,
        help="行情源：auto=akshare 优先，失败回退 OpenBB",
    )
    an.add_argument(
        "--no-openbb",
        action="store_true",
        help="Skip OpenBB news/profile enrichment in report",
    )
    an.add_argument("--no-benchmark", action="store_true")
    an.add_argument("--no-ml", action="store_true", help="Skip qlib Alpha158 ML")
    an.add_argument(
        "--ml-algo",
        choices=["xgb", "lgb", "both"],
        default="both",
        help="ML model: xgboost, lightgbm, or both",
    )
    an.add_argument("--md-only", action="store_true", help="Print markdown report only")

    ml = sub.add_parser("ml", help="qlib Alpha158 + XGB/LGB ML on local qlib data")
    ml.add_argument("--code", required=True)
    ml.add_argument("--start", default="2020-01-01")
    ml.add_argument("--end", default=None)
    ml.add_argument("--data-dir", default="data/stocks")
    ml.add_argument("--algo", choices=["xgb", "lgb", "both"], default="both")

    macro = sub.add_parser("macro", help="OpenBB macro / industry panel (no full analyze)")
    macro.add_argument(
        "--code",
        default=None,
        help="Optional A-share code for industry context + FMP peers",
    )
    macro.add_argument(
        "--countries",
        nargs="*",
        default=["china", "united_states"],
        help="econdb country_profile countries",
    )
    macro.add_argument("--fred-start", default="2020-01-01", help="FRED series start date")
    macro.add_argument("--no-fred", action="store_true", help="Skip FRED even if key set")
    macro.add_argument("--no-fmp-peers", action="store_true", help="Skip FMP peers lookup")
    macro.add_argument(
        "--output",
        default="data/macro",
        help="Write panel.json / panel.md here",
    )
    macro.add_argument("--no-save", action="store_true", help="Print only, do not write files")
    macro.add_argument("--md-only", action="store_true", help="Print markdown only")

    obb = sub.add_parser("openbb", help="OpenBB capabilities & research bundle")
    obb_sub = obb.add_subparsers(dest="obb_cmd", required=True)
    obb_caps = obb_sub.add_parser("caps", help="List integrated OpenBB features")
    obb_caps.add_argument("--probe", action="store_true", help="Probe availability")
    obb_re = obb_sub.add_parser("research", help="Fetch full OpenBB research for one stock")
    obb_re.add_argument("--code", required=True)
    obb_re.add_argument("--no-fred", action="store_true")
    obb_re.add_argument("--json-only", action="store_true")

    crypto = sub.add_parser("crypto", help="Crypto: ccxt analyze & Binance bot")
    crypto_sub = crypto.add_subparsers(dest="crypto_cmd", required=True)

    cr_an = crypto_sub.add_parser("analyze", help="BTC/ETH analysis + 看涨/看跌")
    cr_an.add_argument("--symbol", default="BTC", help="BTC, ETH, SOL ...")
    cr_an.add_argument("--timeframe", default="1d")
    cr_an.add_argument("--limit", type=int, default=500)
    cr_an.add_argument("--data-dir", default="data/crypto")
    cr_an.add_argument("--no-ml", action="store_true", help="Skip qlib Alpha158 ML")
    cr_an.add_argument(
        "--no-options-vol",
        action="store_true",
        help="不并入 Binance 期权 IV 联合研判",
    )
    cr_an.add_argument(
        "--ml-algo",
        choices=["xgb", "lgb", "both"],
        default="both",
        help="qlib ML: xgb | lgb | both",
    )
    cr_an.add_argument("--md-only", action="store_true")

    cr_ml = crypto_sub.add_parser("ml", help="qlib ML on local crypto qlib data")
    cr_ml.add_argument("--symbol", default="BTC")
    cr_ml.add_argument("--data-dir", default="data/crypto")
    cr_ml.add_argument("--algo", choices=["xgb", "lgb", "both"], default="both")

    cr_bot = crypto_sub.add_parser("bot", help="Binance spot bot (default dry-run)")
    cr_bot.add_argument("--symbol", default="BTC")
    cr_bot.add_argument("--quote", default="USDT")
    cr_bot.add_argument("--amount", type=float, default=50.0, help="Buy size in USDT")
    cr_bot.add_argument("--timeframe", default="1d")
    cr_bot.add_argument("--signal-only", action="store_true", help="Only print signal")
    cr_bot.add_argument(
        "--use-ml",
        action="store_true",
        help="Use local qlib ML + technical combined signal",
    )
    cr_bot.add_argument("--data-dir", default="data/crypto")
    cr_bot.add_argument("--live", action="store_true", help="REAL orders (dangerous)")
    cr_bot.add_argument("--testnet", action="store_true", help="Binance testnet")

    cr_perp = crypto_sub.add_parser("perp-bot", help="Binance USDT-M perpetual bot (default dry-run)")
    cr_perp.add_argument("--base", default="BTC")
    cr_perp.add_argument("--quote", default="USDT")
    cr_perp.add_argument("--timeframe", default="5m")
    cr_perp.add_argument("--interval-minutes", type=int, default=10)
    cr_perp.add_argument("--ohlcv-limit", type=int, default=800)
    cr_perp.add_argument("--leverage", type=int, default=3)
    cr_perp.add_argument("--risk-fraction", type=float, default=0.20)
    cr_perp.add_argument("--min-notional", type=float, default=10.0)
    cr_perp.add_argument(
        "--max-daily-loss-pct",
        type=float,
        default=0.03,
        help="日内亏损熔断阈值（0=关闭），触发后仅允许平仓",
    )
    cr_perp.add_argument("--sl-pct", type=float, default=0.01, help="止损百分比（pct 模式或 hybrid 回退）")
    cr_perp.add_argument("--tp-pct", type=float, default=0.015, help="止盈百分比（pct 模式）")
    cr_perp.add_argument(
        "--sizing-mode",
        choices=["leverage_fraction", "atr", "hybrid"],
        default="hybrid",
        help="开仓名义：leverage_fraction | atr（波动止损定仓）| hybrid（ATR 且不超过杠杆上限）",
    )
    cr_perp.add_argument("--atr-period", type=int, default=14, help="ATR 周期（K 线根数）")
    cr_perp.add_argument("--sl-atr", type=float, default=1.5, help="止损 ATR 倍数（sizing + SL）")
    cr_perp.add_argument("--tp-atr", type=float, default=2.5, help="止盈 ATR 倍数")
    cr_perp.add_argument(
        "--no-atr-sl-tp",
        action="store_true",
        help="保护单使用固定 sl-pct/tp-pct，不用 ATR",
    )
    cr_perp.add_argument("--max-protection-failures", type=int, default=3, help="保护单连续失败 N 次后强平")
    cr_perp.add_argument(
        "--no-telemetry",
        action="store_true",
        help="禁用 JSONL 遥测（默认写入 data/crypto/perp_logs/YYYYMMDD.jsonl）",
    )
    cr_perp.add_argument("--telemetry-dir", default="data/crypto/perp_logs", help="JSONL 日志目录")
    cr_perp.add_argument("--signal-only", action="store_true")
    cr_perp.add_argument("--once", action="store_true", help="Run one cycle then exit")
    cr_perp.add_argument("--live", action="store_true", help="REAL orders (dangerous)")
    cr_perp.add_argument("--testnet", action="store_true")
    cr_perp.add_argument("--ccxt-symbol", default="", help="Override ccxt symbol, e.g. BTC/USDT:USDT")

    cr_perp_pf = crypto_sub.add_parser(
        "perp-portfolio",
        help="多标的永续 bot（组合预算 + 并发仓位约束，默认 dry-run）",
    )
    cr_perp_pf.add_argument("--symbols", nargs="+", default=["BTC", "ETH"], help="BTC ETH ...")
    cr_perp_pf.add_argument("--quote", default="USDT")
    cr_perp_pf.add_argument("--timeframe", default="5m")
    cr_perp_pf.add_argument("--ohlcv-limit", type=int, default=800)
    cr_perp_pf.add_argument("--leverage", type=int, default=3)
    cr_perp_pf.add_argument("--risk-fraction", type=float, default=0.20, help="单 bot 风险占比（与 perp-bot 一致）")
    cr_perp_pf.add_argument("--total-notional", type=float, default=0.0, help="组合总名义预算 USDT（0=不限制分配层）")
    cr_perp_pf.add_argument("--max-per-symbol-notional", type=float, default=0.0, help="单标的分配上限（0=不限制）")
    cr_perp_pf.add_argument("--max-concurrent", type=int, default=0, help="最大同时持仓标的数（0=不限制）")
    cr_perp_pf.add_argument("--min-notional", type=float, default=10.0)
    cr_perp_pf.add_argument("--signal-only", action="store_true")
    cr_perp_pf.add_argument("--once", action="store_true", help="只跑一轮后退出")
    cr_perp_pf.add_argument("--live", action="store_true", help="REAL orders (dangerous)")
    cr_perp_pf.add_argument("--testnet", action="store_true")
    cr_perp_pf.add_argument("--data-dir", default="data/crypto")
    cr_perp_pf.add_argument("--no-telemetry", action="store_true")
    cr_perp_pf.add_argument("--telemetry-dir", default="data/crypto/perp_logs")

    cr_ping = crypto_sub.add_parser("ping", help="检测 Binance/ccxt 连接（exchangeInfo + 样例 K 线）")
    cr_ping.add_argument("--exchange", choices=["binance", "okx", "bybit"], default="binance")
    cr_ping.add_argument("--symbol", default="BTC")
    cr_ping.add_argument("--timeframe", default="5m")
    cr_ping.add_argument("--no-ohlcv", action="store_true", help="仅测 exchangeInfo")

    cr_opt = crypto_sub.add_parser(
        "options-scan",
        help="Binance 期权 ATM IV 扫描 + 波动告警 + 研究性建议",
    )
    cr_opt.add_argument(
        "--symbols",
        default="BTC,ETH,SOL,BNB",
        help="逗号分隔标的，如 BTC,ETH",
    )
    cr_opt.add_argument("--lookback", type=int, default=None, help="IV 分位回看天数")
    cr_opt.add_argument("--data-dir", default="data/crypto")
    cr_opt.add_argument("--no-persist", action="store_true", help="不写入本地 IV 历史")

    cr_opt_cmp = crypto_sub.add_parser(
        "options-compare",
        help="Binance × Deribit 跨所 ATM IV 对比（同到期对齐）",
    )
    cr_opt_cmp.add_argument(
        "--symbols",
        default="BTC,ETH,SOL,BNB",
        help="逗号分隔标的，如 BTC,ETH",
    )
    cr_opt_cmp.add_argument("--base", default=None, help="单标的对比，如 BTC")
    cr_opt_cmp.add_argument("--data-dir", default="data/crypto")
    cr_opt_cmp.add_argument("--no-persist", action="store_true", help="不写入价差历史 JSONL")

    cr_sched = crypto_sub.add_parser(
        "schedule",
        help="每 N 分钟增量拉取 5m K 线 → qlib → 技术面+ML 投资建议",
    )
    cr_sched.add_argument("--symbols", nargs="+", default=["BTC", "ETH"], help="BTC ETH ...")
    cr_sched.add_argument("--timeframe", default="5m")
    cr_sched.add_argument("--interval-minutes", type=int, default=30)
    cr_sched.add_argument("--backfill-days", type=int, default=90, help="首次回填历史天数")
    cr_sched.add_argument("--data-dir", default="data/crypto")
    cr_sched.add_argument("--no-ml", action="store_true")
    cr_sched.add_argument("--ml-algo", choices=["xgb", "lgb", "both"], default="both")
    cr_sched.add_argument("--once", action="store_true", help="只跑一轮后退出")
    cr_sched.add_argument("--json-only", action="store_true")
    cr_sched.add_argument(
        "--skip-ping",
        action="store_true",
        help="跳过启动前 Binance 连接自检",
    )

    sched_sub = cr_sched.add_subparsers(dest="sched_cmd", required=False)
    sched_list = sched_sub.add_parser("list", help="列出已注册的定时任务")
    sched_list.add_argument("--data-dir", default="data/crypto")

    sched_add = sched_sub.add_parser("add", help="新增定时任务（默认不自动启动）")
    sched_add.add_argument("--symbols", nargs="+", required=True)
    sched_add.add_argument("--name", default="")
    sched_add.add_argument("--id", default="")
    sched_add.add_argument("--timeframe", default="5m")
    sched_add.add_argument("--interval-minutes", type=int, default=30)
    sched_add.add_argument("--backfill-days", type=int, default=90)
    sched_add.add_argument("--data-dir", default="data/crypto")
    sched_add.add_argument("--no-ml", action="store_true")
    sched_add.add_argument("--ml-algo", choices=["xgb", "lgb", "both"], default="both")
    sched_add.add_argument("--auto-start", action="store_true", help="创建后立即启动")

    sched_start = sched_sub.add_parser("start", help="启动定时任务")
    sched_start.add_argument("--id", required=True)
    sched_start.add_argument("--data-dir", default="data/crypto")

    sched_stop = sched_sub.add_parser("stop", help="停止定时任务")
    sched_stop.add_argument("--id", required=True)
    sched_stop.add_argument("--data-dir", default="data/crypto")

    sched_rm = sched_sub.add_parser("remove", help="删除定时任务")
    sched_rm.add_argument("--id", required=True)
    sched_rm.add_argument("--data-dir", default="data/crypto")

    sched_once = sched_sub.add_parser("run-once", help="对已有任务手动执行一轮")
    sched_once.add_argument("--id", required=True)
    sched_once.add_argument("--data-dir", default="data/crypto")
    sched_once.add_argument("--json-only", action="store_true")

    args = p.parse_args()
    if args.cmd == "analyze":
        from quant_rd_tool.stock_analysis import analyze_stock

        provider: DataProvider = args.provider or settings.data_provider  # type: ignore[assignment]
        report = analyze_stock(
            args.code,
            start_date=args.start,
            end_date=args.end,
            data_dir=args.data_dir,
            refresh=args.refresh,
            with_benchmark=not args.no_benchmark,
            with_ml=not args.no_ml,
            ml_algorithm=args.ml_algo,
            data_provider=provider,
            with_openbb_enrichment=not args.no_openbb,
        )
        if args.md_only:
            print(report["markdown"])
        else:
            import json

            out = {k: v for k, v in report.items() if k != "markdown"}
            print(json.dumps(out, ensure_ascii=False, indent=2))
            print("\n--- report.md ---\n")
            print(report["markdown"])
        return

    if args.cmd == "ml":
        import json
        from pathlib import Path

        from quant_rd_tool import akshare_data as ak_data
        from quant_rd_tool.qlib_ml import run_ml_analysis
        from quant_rd_tool.stock_storage import csv_path, load_csv, qlib_path, stock_root

        end = args.end or __import__("datetime").date.today().isoformat()
        root = stock_root(args.data_dir, args.code)
        if not csv_path(root).exists():
            raise SystemExit(f"无本地数据，请先运行: quant-rd analyze --code {args.code}")
        df = load_csv(csv_path(root))
        result = run_ml_analysis(
            str(qlib_path(root).resolve()),
            ak_data.to_qlib_code(args.code),
            start_date=args.start,
            end_date=end,
            num_bars=len(df),
            algorithm=args.algo,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "openbb":
        import json

        from quant_rd_tool.openbb_research import build_openbb_research, get_capabilities_report

        if args.obb_cmd == "caps":
            print(json.dumps(get_capabilities_report(probe=args.probe), ensure_ascii=False, indent=2))
            return
        if args.obb_cmd == "research":
            data = build_openbb_research(args.code, use_fred=not args.no_fred)
            if args.json_only:
                print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
            else:
                from quant_rd_tool.openbb_research import render_openbb_markdown

                print(json.dumps({k: v for k, v in data.items() if k != "capabilities"}, ensure_ascii=False, indent=2, default=str))
                print("\n--- markdown ---\n")
                print(render_openbb_markdown(data))
            return

    if args.cmd == "macro":
        import json

        from quant_rd_tool.macro_panel import build_macro_panel, save_macro_panel

        try:
            panel = build_macro_panel(
                code=args.code,
                countries=tuple(args.countries),
                use_fred=not args.no_fred,
                fred_start_date=args.fred_start,
                use_fmp_peers=not args.no_fmp_peers,
            )
        except ImportError as e:
            raise SystemExit(str(e)) from e

        if not args.no_save:
            paths = save_macro_panel(panel, args.output)
            if args.md_only:
                print(panel["markdown"])
                return
            out = {k: v for k, v in panel.items() if k != "markdown"}
            out["saved"] = paths
            print(json.dumps(out, ensure_ascii=False, indent=2))
            print("\n--- panel.md ---\n")
            print(panel["markdown"])
            return

        if args.md_only:
            print(panel["markdown"])
        else:
            out = {k: v for k, v in panel.items() if k != "markdown"}
            print(json.dumps(out, ensure_ascii=False, indent=2))
            print("\n--- panel.md ---\n")
            print(panel["markdown"])
        return

    if args.cmd == "crypto":
        import json

        if args.crypto_cmd == "ping":
            from quant_rd_tool.ccxt_connectivity import check_connectivity

            report = check_connectivity(
                args.exchange,  # type: ignore[arg-type]
                test_ohlcv=not args.no_ohlcv,
                symbol=args.symbol,
                timeframe=args.timeframe,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if not report.get("ok"):
                raise SystemExit(1)
            return

        if args.crypto_cmd == "options-scan":
            from quant_rd_tool.crypto_options_advisor import build_scan_advice
            from quant_rd_tool.crypto_options_vol_scan import run_volatility_scan

            sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()]
            scan = run_volatility_scan(
                symbols=sym_list,
                lookback_days=args.lookback,
                data_dir=args.data_dir,
                persist_snapshot=not args.no_persist,
            )
            out = {**scan, "advice_pack": build_scan_advice(scan)}
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return

        if args.crypto_cmd == "options-compare":
            from quant_rd_tool.crypto_options_compare import (
                build_venue_compare,
                build_venue_compare_scan,
            )

            if args.base:
                out = build_venue_compare(args.base.strip().upper())
            else:
                sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()]
                out = build_venue_compare_scan(
                    sym_list,
                    data_dir=args.data_dir,
                    persist_spread=not args.no_persist,
                )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return

        if args.crypto_cmd == "analyze":
            from quant_rd_tool.crypto_analysis import analyze_crypto

            report = analyze_crypto(
                args.symbol,
                data_dir=args.data_dir,
                timeframe=args.timeframe,
                limit=args.limit,
                with_ml=not args.no_ml,
                ml_algorithm=args.ml_algo,
                with_options_vol=not args.no_options_vol,
            )
            if args.md_only:
                print(report["markdown"])
            else:
                out = {k: v for k, v in report.items() if k != "markdown"}
                print(json.dumps(out, ensure_ascii=False, indent=2))
                print("\n--- report.md ---\n")
                print(report["markdown"])
            return

        if args.crypto_cmd == "ml":
            import json
            from pathlib import Path

            import pandas as pd

            from quant_rd_tool import ccxt_data as cxt
            from quant_rd_tool.crypto_ml import run_crypto_ml_analysis

            root = Path(args.data_dir) / cxt.to_qlib_code(args.symbol)
            csv_file = root / "ohlcv.csv"
            qlib_dir = root / "qlib"
            if not csv_file.exists():
                raise SystemExit(
                    f"无本地数据，请先: quant-rd crypto analyze --symbol {args.symbol} --limit 500"
                )
            df = pd.read_csv(csv_file)
            df["date"] = pd.to_datetime(df["date"])
            result = run_crypto_ml_analysis(
                str(qlib_dir.resolve()),
                cxt.to_qlib_code(args.symbol),
                start_date=str(df["date"].min().date()),
                end_date=str(df["date"].max().date()),
                num_bars=len(df),
                algorithm=args.algo,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        if args.crypto_cmd == "bot":
            from quant_rd_tool.binance_bot import BinanceBot, BotConfig

            cfg = BotConfig(
                symbol=args.symbol,
                quote=args.quote,
                quote_amount=args.amount,
                timeframe=args.timeframe,
                dry_run=not args.live,
                testnet=args.testnet or settings.binance_testnet,
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
            )
            bot = BinanceBot(cfg)
            if args.signal_only:
                sig = bot.fetch_signal(use_ml=args.use_ml, data_dir=args.data_dir)
                print(json.dumps(sig, ensure_ascii=False, indent=2, default=str))
                return
            if args.live and not (settings.binance_api_key and settings.binance_api_secret):
                raise SystemExit("实盘需要 .env 中 BINANCE_API_KEY / BINANCE_API_SECRET")
            result = bot.run_once()
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return

        if args.crypto_cmd == "perp-bot":
            from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig

            if args.live and not (settings.binance_api_key and settings.binance_api_secret):
                raise SystemExit("实盘需要 .env 中 BINANCE_API_KEY / BINANCE_API_SECRET")

            cfg = PerpBotConfig(
                base=args.base,
                quote=args.quote,
                timeframe=args.timeframe,
                interval_minutes=args.interval_minutes,
                ohlcv_limit=args.ohlcv_limit,
                leverage=args.leverage,
                usdt_risk_fraction=args.risk_fraction,
                min_notional_usdt=args.min_notional,
                max_daily_loss_pct=args.max_daily_loss_pct,
                sl_pct=args.sl_pct,
                tp_pct=args.tp_pct,
                sizing_mode=args.sizing_mode,
                atr_period=args.atr_period,
                sl_atr=args.sl_atr,
                tp_atr=args.tp_atr,
                use_atr_sl_tp=not args.no_atr_sl_tp,
                max_protection_failures=args.max_protection_failures,
                telemetry_enabled=not args.no_telemetry,
                telemetry_log_dir=args.telemetry_dir,
                dry_run=not args.live,
                testnet=args.testnet or settings.binance_testnet,
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
                ccxt_symbol=args.ccxt_symbol,
            )
            bot = BinancePerpBot(cfg)
            if args.signal_only:
                sig = bot.fetch_signal()
                print(json.dumps(sig, ensure_ascii=False, indent=2, default=str))
                return
            if args.once:
                out = bot.run_once()
                print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
                return
            print(f"前台运行永续 bot（Ctrl+C 停止）: {cfg.base} {cfg.timeframe} every {cfg.interval_minutes}m")
            try:
                bot.run_forever()
            except KeyboardInterrupt:
                print("\n已停止")
            return

        if args.crypto_cmd == "perp-portfolio":
            import json

            from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig
            from quant_rd_tool.perp_portfolio import PortfolioRunConfig, run_portfolio_once
            from quant_rd_tool.perp_telemetry import PerpTelemetry, TelemetryConfig

            if args.live and not (settings.binance_api_key and settings.binance_api_secret):
                raise SystemExit("实盘需要 .env 中 BINANCE_API_KEY / BINANCE_API_SECRET")

            symbols = [s.strip().upper() for s in args.symbols if s and s.strip()]
            bots: dict[str, BinancePerpBot] = {}
            for sym in symbols:
                cfg = PerpBotConfig(
                    base=sym,
                    quote=args.quote,
                    timeframe=args.timeframe,
                    ohlcv_limit=args.ohlcv_limit,
                    leverage=args.leverage,
                    usdt_risk_fraction=args.risk_fraction,
                    min_notional_usdt=args.min_notional,
                    sizing_mode=getattr(args, "sizing_mode", "hybrid"),
                    atr_period=getattr(args, "atr_period", 14),
                    sl_atr=getattr(args, "sl_atr", 1.5),
                    tp_atr=getattr(args, "tp_atr", 2.5),
                    use_atr_sl_tp=not getattr(args, "no_atr_sl_tp", False),
                    telemetry_enabled=not getattr(args, "no_telemetry", False),
                    telemetry_log_dir=getattr(args, "telemetry_dir", "data/crypto/perp_logs"),
                    dry_run=not args.live,
                    testnet=args.testnet or settings.binance_testnet,
                    api_key=settings.binance_api_key,
                    api_secret=settings.binance_api_secret,
                )
                bots[sym] = BinancePerpBot(cfg)

            telemetry = PerpTelemetry(
                TelemetryConfig(
                    enabled=not getattr(args, "no_telemetry", False),
                    log_dir=getattr(args, "telemetry_dir", "data/crypto/perp_logs"),
                )
            )
            pf_cfg = PortfolioRunConfig(
                symbols=symbols,
                total_notional_usdt=float(args.total_notional or 0),
                max_per_symbol_notional_usdt=float(args.max_per_symbol_notional or 0),
                max_concurrent_positions=int(args.max_concurrent or 0),
            )
            out = run_portfolio_once(
                bots, config=pf_cfg, signal_only=args.signal_only, telemetry=telemetry
            )
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            return

        if args.crypto_cmd == "schedule":
            import json

            from quant_rd_tool.crypto_scheduler import run_scheduled_cycle, run_scheduler
            from quant_rd_tool.scheduler_manager import ScheduleJobConfig, get_scheduler_manager, reset_scheduler_manager

            sched_cmd = getattr(args, "sched_cmd", None)

            if sched_cmd == "list":
                reset_scheduler_manager()
                mgr = get_scheduler_manager(args.data_dir)
                jobs = mgr.list_jobs()
                print(json.dumps({"count": len(jobs), "jobs": jobs}, ensure_ascii=False, indent=2))
                return

            if sched_cmd == "add":
                reset_scheduler_manager()
                mgr = get_scheduler_manager(args.data_dir)
                cfg = ScheduleJobConfig(
                    symbols=args.symbols,
                    name=args.name,
                    id=args.id,
                    timeframe=args.timeframe,
                    interval_minutes=args.interval_minutes,
                    backfill_days=args.backfill_days,
                    data_dir=args.data_dir,
                    with_ml=not args.no_ml,
                    ml_algorithm=args.ml_algo,
                )
                job = mgr.add_job(cfg, auto_start=args.auto_start)
                print(json.dumps(job, ensure_ascii=False, indent=2))
                return

            if sched_cmd == "start":
                mgr = get_scheduler_manager(args.data_dir)
                job = mgr.get_job(args.id)
                if not job:
                    raise SystemExit(f"未找到任务: {args.id}")
                print(f"前台运行任务 {args.id}（Ctrl+C 停止）")
                try:
                    run_scheduler(
                        job["symbols"],
                        data_dir=job["data_dir"],
                        timeframe=job["timeframe"],
                        interval_minutes=job["interval_minutes"],
                        backfill_days=job["backfill_days"],
                        with_ml=job["with_ml"],
                        ml_algorithm=job["ml_algorithm"],
                        once=False,
                        precheck_connectivity=True,
                    )
                except KeyboardInterrupt:
                    print("\n已停止")
                return

            if sched_cmd == "stop":
                reset_scheduler_manager()
                mgr = get_scheduler_manager(args.data_dir)
                print(json.dumps(mgr.stop_job(args.id), ensure_ascii=False, indent=2))
                print("提示：仅对 API 服务内后台任务生效；CLI 前台任务请用 Ctrl+C")
                return

            if sched_cmd == "remove":
                reset_scheduler_manager()
                mgr = get_scheduler_manager(args.data_dir)
                print(json.dumps(mgr.remove_job(args.id), ensure_ascii=False, indent=2))
                return

            if sched_cmd == "run-once":
                reset_scheduler_manager()
                mgr = get_scheduler_manager(args.data_dir)
                payload = mgr.run_once(args.id)
                if args.json_only:
                    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
                else:
                    for row in payload.get("results", []):
                        if row.get("error"):
                            print(f"[ERROR] {row.get('symbol')}: {row['error']}")
                        else:
                            sig = row.get("combined_signal", {})
                            print(f"{row.get('pair')}: {sig.get('stance')} ({sig.get('action')})")
                return

            if args.once:
                results = run_scheduled_cycle(
                    args.symbols,
                    data_dir=args.data_dir,
                    timeframe=args.timeframe,
                    backfill_days=args.backfill_days,
                    with_ml=not args.no_ml,
                    ml_algorithm=args.ml_algo,
                    precheck_connectivity=not args.skip_ping,
                )
                if args.json_only:
                    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
                else:
                    for r in results:
                        if r.get("error"):
                            print(f"[ERROR] {r.get('symbol')}: {r['error']}")
                            continue
                        sig = r.get("combined_signal", {})
                        sync = r.get("sync", {})
                        print(
                            f"{r.get('pair')}: {sig.get('stance')} ({sig.get('action')}) "
                            f"| +{sync.get('new_bars', 0)} bars | {r.get('narrative', {}).get('advice', '')}"
                        )
                return

            run_scheduler(
                args.symbols,
                data_dir=args.data_dir,
                timeframe=args.timeframe,
                interval_minutes=args.interval_minutes,
                backfill_days=args.backfill_days,
                with_ml=not args.no_ml,
                ml_algorithm=args.ml_algo,
                once=False,
                precheck_connectivity=not args.skip_ping,
            )
            return

    if args.cmd == "backtest":
        from quant_rd_tool.backtest_engine import run_backtest

        provider: DataProvider = args.provider or settings.data_provider  # type: ignore[assignment]
        result = run_backtest(
            args.symbols,
            start_date=args.start,
            end_date=args.end,
            lookback=args.lookback,
            topk=args.topk,
            signal_mode=args.signal,
            ml_algorithm=args.ml_algo,
            data_provider=provider,
        )
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "serve":
        use_reload = bool(getattr(args, "reload", False))
        uvicorn.run(
            "quant_rd_tool.main:app",
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=use_reload,
            reload_dirs=[os.path.dirname(os.path.abspath(__file__))] if use_reload else None,
        )


if __name__ == "__main__":
    main()
