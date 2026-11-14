"""Washout-dip BTC bot for make.fun btc-race-24h-20261113-2314.

Trades cbBTC/USDC on 1-minute bars, long only, one position, all-in sizing.
Standard library only; fully deterministic (no clock, no randomness, no
environment, no network). Speaks agent-fun/bars-replay/v1 on stdin/stdout.

STRATEGY (dip-first, two entry legs, one shared exit)
  1. Washout dip (the main leg): buy when the close sits at least 1.20% below
     the trailing 60-bar high AND the last 15 bars fell at least 0.50% --
     a sharp washout, not a slow grind down. A deep washout also satisfies
     the 1.20% trigger, so the leg fires on capitulation-sized drops too.
  2. Momentum ignition (the secondary leg): buy when the trailing 60-minute
     close-to-close return reaches +0.50% -- a real hourly move, not noise
     (a 1-minute bar's return SD is only ~5 bps).
  Exits (either leg): sell everything at +0.70% vs the entry close, at
  -0.60%, or after 120 bars, then sit out 60 bars (no churn in chop).
  A full round trip costs ~26 bps in fee + slippage + pool impact, so both
  legs only fire on moves comfortably larger than that.

Orders decided on bar k fill at bar k+1's open; max_slippage_bps is 100
(1%) so a normal 1-minute gap never rejects a fill, while a violent gap
does. One order per reply at most.
"""

import json
import sys

SYMBOL = "CBBTC"

# --- strategy parameters, re-derived by backtesting on the proxy dev window
# (the previous race's 1,439-bar window; the new race's dev window is not
# published locally). See README.md for the grid and robustness numbers.
DIP_WINDOW = 60        # bars of trailing high for the dip leg
DIP_BPS = 120          # close must be >= 1.20% below the trailing high
FAST_WINDOW = 15       # bars for the washout-speed filter
FAST_BPS = 50          # ... which must have fallen >= 0.50%
MOM_WINDOW = 60        # bars for the momentum leg
MOM_BPS = 50           # trailing return must reach +0.50%
TAKE_PROFIT_BPS = 70   # exit at +0.70% vs entry close
STOP_LOSS_BPS = 60     # exit at -0.60% vs entry close
HOLD_TIMEOUT = 120     # exit after 120 bars whatever the price
COOLDOWN = 60          # bars to sit out after any exit
MAX_SLIPPAGE_BPS = 100

BPS = 10_000


class WashoutBot:
    """Keeps the bar history and the position state; one decision per batch."""

    def __init__(self, hello):
        self.hello = hello
        self.warmup_bars = hello.get("warmup_bars", 0) or 0
        self.closes = []          # CBBTC closes, in bar order (ints, price scale 5)
        self.bar_index = -1       # 0-based index of the latest CBBTC bar
        self.cash = int(hello["capital"]["quote_units"])
        self.qty = 0              # held CBBTC qty (qty scale 8)
        self.entry_close = 0      # close at the bar the entry was decided on
        self.entry_bar = -1       # bar index the entry was decided on
        self.cooldown_until = -1  # no new entry while bar_index < this
        self._pending_buy = None  # (close, bar_index) of a buy awaiting its fill
        self._order_no = 0

    # -- history helpers -------------------------------------------------
    def _trailing_high(self, window):
        window = min(window, len(self.closes))
        return max(self.closes[-window:])

    def _dip_trigger(self):
        high = self._trailing_high(DIP_WINDOW)
        if self.closes[-1] * BPS > high * (BPS - DIP_BPS):
            return False
        # washout speed: the last FAST_WINDOW bars must themselves have fallen
        ref = self.closes[-1 - FAST_WINDOW]
        return self.closes[-1] * BPS <= ref * (BPS - FAST_BPS)

    def _momentum_trigger(self):
        ref = self.closes[-1 - MOM_WINDOW]
        return self.closes[-1] * BPS >= ref * (BPS + MOM_BPS)

    def _exit_trigger(self):
        close = self.closes[-1]
        if close * BPS >= self.entry_close * (BPS + TAKE_PROFIT_BPS):
            return True
        if close * BPS <= self.entry_close * (BPS - STOP_LOSS_BPS):
            return True
        return (self.bar_index - self.entry_bar) >= HOLD_TIMEOUT

    # -- protocol state --------------------------------------------------
    def apply_batch(self, batch):
        for bar in batch.get("bars", []):
            if bar.get("symbol") == SYMBOL:
                self.closes.append(int(bar["c"]))
                self.bar_index += 1
        account = batch.get("account", {})
        self.cash = int(account.get("cash_quote_units", self.cash))
        self.qty = 0
        for pos in account.get("positions", []):
            if pos.get("symbol") == SYMBOL:
                self.qty = int(pos["qty"])
        # Commit a pending buy only once its fill actually shows up; a
        # rejected buy leaves no position and no entry state behind.
        if self._pending_buy is not None:
            if self.qty > 0:
                self.entry_close, self.entry_bar = self._pending_buy
            self._pending_buy = None

    def decide(self, seq):
        """The orders for this batch (at most one)."""
        if seq < self.warmup_bars:
            return []
        if not self.closes:
            return []
        if self.qty == 0:
            if self.bar_index < self.cooldown_until:
                return []
            if self.bar_index < max(DIP_WINDOW, FAST_WINDOW, MOM_WINDOW):
                return []
            if self._dip_trigger() or self._momentum_trigger():
                return [self._buy(self.cash)]
            return []
        # holding: exit checks against the entry close
        if self._exit_trigger():
            self.cooldown_until = self.bar_index + COOLDOWN
            return [self._sell(self.qty)]
        return []

    def _buy(self, notional):
        self._order_no += 1
        self._pending_buy = (self.closes[-1], self.bar_index)
        return {
            "side": "buy",
            "client_id": "b%d" % self._order_no,
            "symbol": SYMBOL,
            "notional_quote_units": str(int(notional)),
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }

    def _sell(self, qty):
        self._order_no += 1
        return {
            "side": "sell",
            "client_id": "s%d" % self._order_no,
            "symbol": SYMBOL,
            "qty": str(int(qty)),
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }


def _reply(seq, orders):
    line = json.dumps({"type": "reply", "seq": seq, "orders": orders},
                      separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main():
    bot = None
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            if msg.get("protocol") != "agent-fun/bars-replay/v1":
                raise ValueError("unknown protocol: %r" % (msg.get("protocol"),))
            bot = WashoutBot(msg)
        elif kind == "batch":
            if bot is None:
                raise ValueError("batch before hello")
            bot.apply_batch(msg)
            _reply(msg["seq"], bot.decide(msg["seq"]))
        elif kind == "done":
            return 0
        else:
            raise ValueError("unknown message type: %r" % (kind,))
    raise ValueError("input ended before done")


if __name__ == "__main__":
    sys.exit(main())
