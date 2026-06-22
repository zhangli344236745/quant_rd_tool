/** Carry 套利页面术语说明（中文备注） */

export const CARRY_GLOSSARY = [
  {
    term: "Cash & Carry / 套息套利",
    desc: "同时买入现货、做空等量永续，整体涨跌风险相互抵消，主要赚资金费率和基差变化。本页为纸面模拟，不下真实单。",
  },
  {
    term: "Watchlist / 监控列表",
    desc: "要扫描的币种列表，例如 BTC、ETH。只会对这些币计算机会。",
  },
  {
    term: "名义金额 (Notional)",
    desc: "模拟仓位使用的 USDT 规模。例如 10,000 表示约 1 万 U 的现货多头 + 等量永续空头。",
  },
  {
    term: "基差 (Basis)",
    desc: "永续价格相对现货高多少。公式：(永续价 − 现货价) ÷ 现货价。单位 bps：1 bps = 0.01%。正数表示永续比现货贵。",
  },
  {
    term: "资金费率 (Funding)",
    desc: "永续合约每 8 小时在多空之间结算一次。费率为正时，做空方收取费用；为负时做空方需支付。",
  },
  {
    term: "Funding APR",
    desc: "把当前 8 小时资金费率换算成「年化收益率」的估算值，便于和理财利率对比。",
  },
  {
    term: "Composite APR / 综合年化",
    desc: "Funding APR + 基差年化参考。用于判断是否达到入场/退出阈值；基差部分不保证能兑现。",
  },
  {
    term: "入场 / 退出阈值",
    desc: "综合年化 ≥ 入场线时标为「可入场」；持仓中综合年化 ≤ 退出线或 funding 转负时提示关注退出。仍需手动确认。",
  },
  {
    term: "已实现盈亏",
    desc: "已平仓纸面仓位的最终盈亏（funding + 基差 − 手续费），已写入账本。",
  },
  {
    term: "Pending funding",
    desc: "自上次 8 小时结算点以来、尚未入账的 funding 估算，平仓时会一并结算进盈亏。",
  },
] as const;

export const CARRY_TERM_HINTS = {
  watchlist: "要扫描的币种，逗号分隔，如 BTC, ETH, SOL",
  entryApr: "综合年化达到此值才高亮「可入场」。越高越保守，机会更少。",
  exitApr: "持仓中综合年化低于此值会提示退出关注。",
  notional: "开纸面仓时默认使用的 USDT 名义规模。",
  openCount: "当前尚未平仓的纸面 Carry 笔数。",
  entryAlert: "扫描结果里达到入场阈值的币种数量。",
  realizedPnl: "历史已平仓纸面仓累计盈亏（USDT）。",
  accruedFunding: "所有开放仓已累计的 funding 收入（未平仓）。",
  symbol: "交易对基础币种，如 BTC 表示 BTC/USDT。",
  basisBps: "永续相对现货的溢价，单位 bps（万分之一）。",
  fundingRate: "当前 8 小时资金费率；正数利于做空永续。",
  estDailyFunding: "按当前费率和默认名义，估算一天能收多少 funding（×3 个 8h）。",
  compositeApr: "综合年化收益率，用于入场/退出判断。",
  entryBasis: "开仓时刻记录的基差（bps），平仓时与之对比算基差盈亏。",
  accruedFundingCol: "该笔持仓至今已入账的 funding 累计。",
  pendingFunding: "自上次 8 小时结算以来尚未写入账本的 funding 估算，平仓时会一并结算。",
  exitAlert: "综合收益偏低或 funding 转负时建议关注是否平仓。",
  notionalItem: "本笔纸面仓使用的 USDT 规模。",
  spotMark: "Binance 现货最新价，用于估算开仓/平仓。",
  perpMark: "Binance USDT 永续标记价，用于估算开仓/平仓。",
  holdDays: "从开仓到当前的持仓天数。",
  realizedPnlEst: "若按当前价平仓，预估最终盈亏（含 pending funding）。",
  basisPnl: "基差从开仓到平仓变化带来的盈亏。",
  openCost: "开仓时手续费 + 滑点的模拟成本。",
  roundTripCost: "开仓 + 平仓双边手续费与滑点合计。",
  breakevenDays: "按当前 funding 估算，多少天能覆盖开平仓总成本。",
  funding8h: "每 8 小时结算一次的 funding 收入估算。",
  net7d: "7 日 funding 减去开仓成本后的净额估算。",
  basisAnnualHint: "把当前基差换算成年化参考，不保证能赚到。",
} as const;
