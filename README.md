# Washout-dip BTC bot — make.fun btc-race-24h-20261113-2314

A paper-trading bot for cbBTC/USDC on 1-minute bars. Long only, one
position, all-in sizing, fully deterministic, standard library only.
Nothing here trades for real money.

## Strategy

Dip-first, with a momentum kicker, one shared exit:

1. **Washout dip (main leg).** Buy when the close is at least **1.20% below
   the trailing 60-bar high** and the last **15 bars fell at least 0.50%**.
   The speed filter is the point: a sharp washout, not a slow grind down.
   A deeper capitulation drop also satisfies the 1.20% trigger, so the leg
   fires on washouts of any depth.
2. **Momentum ignition (secondary leg).** Buy when the trailing 60-minute
   close-to-close return reaches **+0.50%** — a real hourly move (a
   1-minute bar's return SD is only ~5 bps), not noise.
3. **Exit (either leg).** Sell everything at **+0.70%** vs the entry close,
   at **-0.60%**, or after **120 bars**; then sit out **60 bars** so the bot
   does not churn in chop.

Orders decided on bar k fill at bar k+1's open. A full round trip costs
~26 bps (4 bps fee + 2 bps slippage + ~7 bps pool impact each way at
$1,000), so both legs only fire on moves comfortably larger than that.
`max_slippage_bps` is 100 (1%): a normal 1-minute gap never rejects a
fill, a violent gap does.

## Why dip-first

The live dev leaderboard for this race (fetched 2026-11-14 ~08:10 WIB,
556 entries) is dominated by deep-dip / capitulation-bounce bots:
ranks 2–10 all run that pattern, net dev PnL **+$28.10 to +$35.20**
(and a new #1, "Certain Nova", at +$64.10). This bot weights the dip leg
accordingly, while keeping a momentum leg so a rallying window is not
missed entirely.

## Backtest (PROXY WINDOW — read this)

The new race's dev window is **not available locally** (the make.fun API
was returning 503 when this was built, and the kit for this race ships no
dataset). All numbers below are on the **previous race's dev window**
(`btc-race-24h-20261112-1439` kit, 1,439 bars, 2026-11-11~12), used as a
proxy. Buy-and-hold on that window is -$25.97, so the proxy window is a
falling market — a hard test for a long-only bot. The new race's dev
window is a different 24 hours; these numbers do **not** transfer
directly, they only show the bot is selective, profitable on a falling
proxy, and robust to parameter changes.

| Metric | Value |
|---|---|
| Net PnL (proxy dev window) | **+$12.02** (+1.20% on $1,000) |
| Trades | 5 trades (3 buys, 2 sells) + final flatten at window end |
| Max drawdown | 0.34% |
| Fees paid | $2.42 |
| Net PnL at 2x fees (8 bps) | **+$9.60** |
| First half (bars 0–719) | +$10.83 |
| Second half (bars 720–1438) | +$1.20 |
| Guardrails | >= 1 trade: yes; maxDD 0.34% <= 25%: yes |

Fills (protocol-validated run of `main.py`):

- BUY bar 62 @ $73,994.49 ($1,000.00) — momentum ignition, early rally
- SELL bar 160 @ $74,659.84
- BUY bar 516 @ $73,448.48 ($1,006.37) — washout dip
- SELL bar 556 @ $73,975.77
- BUY bar 1429 @ $71,724.31 ($1,010.73) — washout dip near the end
- SELL bar 1438 @ $72,044.01 (window flatten)

## Robustness (one parameter at a time off the chosen point)

Dip 100–130 bps: +$8.69 to +$12.02; dip window 60–90 bars: +$7.79 to
+$12.02; momentum 50–70 bps: +$11.09 to +$12.02; take-profit 60–80 bps:
+$11.08 to +$12.05; stop-loss 40–100 bps: identical (+$12.02, never
binds); timeout 120–240 bars: identical; cooldown 60–120 bars:
identical; fast-drop filter 0–50 bps: +$11.92 to +$12.02. Bad
neighbours exist (dip window 120 bars: -$12.43; momentum 40 bps:
+$1.64 with 9 trades; cooldown 0: +$0.67) — the chosen point sits
mid-plateau, not on a spike. Dip-only (no momentum leg) is +$5.63 on
the proxy; the momentum leg adds the early-rally trade. A same-bar
"bounce off the low" confirmation was tested and rejected: it fires
never, because dip bars close near their lows.

## Validation

- Protocol sim: `main.py` run as a subprocess over the real NDJSON
  protocol (hello → 1,439 batches → done) with the exact integer fill
  math from the kit's harness reproduces the backtester **exactly**:
  +$12.02, same 6 fills, exit code 0, empty stderr.
- Determinism: two full protocol runs are byte-identical.
- `python3 -S` (no site-packages) run exits 0 with empty stderr.
- No secrets, API keys, or wallet material anywhere in this repo.

## Run it

The grader runs `python3 -P -s main.py` and speaks
agent-fun/bars-replay/v1 on stdin/stdout. There is nothing to install
and nothing to configure.
