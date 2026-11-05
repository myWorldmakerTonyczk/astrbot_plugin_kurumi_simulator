"""Persist portfolio marks and correlate queued decisions with ledger events."""

import time
from contextvars import ContextVar

decision_scope = ContextVar("kurumi_decision_scope", default=None)


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS replay_equity(
        game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        t INTEGER NOT NULL, equity REAL NOT NULL, return_rate REAL NOT NULL,
        drawdown REAL NOT NULL, PRIMARY KEY(game,t))""")


def sample(db, game, now=None, *, force=False):
    """Persist real marks using the ledger's cash-flow-adjusted index."""
    now = time.time() if now is None else now
    stamp = int(now)
    if not force and db.execute(
        "SELECT 1 FROM replay_equity WHERE game=? AND t>? LIMIT 1", (game["id"], stamp - 60)
    ).fetchone():
        return
    index, peak = float(game["index"]), float(game["peak"])
    drawdown = max(0, (1 - index / peak) * 100)
    db.execute(
        """INSERT INTO replay_equity VALUES(?,?,?,?,?)
           ON CONFLICT(game,t) DO UPDATE SET
           equity=excluded.equity,return_rate=excluded.return_rate,drawdown=excluded.drawdown""",
        (game["id"], stamp, float(game["last_equity"]), (index - 1) * 100, drawdown),
    )
    db.execute("DELETE FROM replay_equity WHERE game=? AND t<?", (game["id"], stamp - 90 * 86400))
