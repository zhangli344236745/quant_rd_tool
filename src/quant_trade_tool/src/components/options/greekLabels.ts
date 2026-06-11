export type GreekKey = "delta" | "gamma" | "theta" | "vega";

export const GREEK_META: Record<
  GreekKey,
  { symbol: string; name: string; hint: string }
> = {
  delta: { symbol: "Δ", name: "Delta", hint: "标的价格敏感度" },
  gamma: { symbol: "Γ", name: "Gamma", hint: "Delta 对价格变化" },
  theta: { symbol: "Θ", name: "Theta", hint: "时间价值衰减" },
  vega: { symbol: "V", name: "Vega", hint: "隐含波动率敏感度" },
};
