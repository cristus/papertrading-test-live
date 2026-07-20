"""Ledger arithmetic and balance reconciliation."""
import os, sys, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import db
from core.broker import PaperBroker, Economics, MarketRules

def make_db(tmp_path):
    return db.init_db(str(tmp_path))

def test_ledger_append_only_blocks_update(tmp_path):
    conn = make_db(tmp_path / "t1.sqlite")
    conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
    conn.commit()
    lid = db.insert_ledger(conn, experiment_id=1, agent_id=1, ts=1, tick_index=0, event_type="DECISION",
                           side=None, market_price=100, quantity=0, gross_amount=0, fee=0, tds=0,
                           slippage_cost=0, cash_balance=2000, position_qty=0, reason="x", detail_json=None)
    conn.commit()
    try:
        conn.execute("UPDATE ledger SET reason='y' WHERE id=?", (lid,))
        conn.commit()
        assert False, "UPDATE should have been blocked"
    except sqlite3.IntegrityError:
        pass

def test_ledger_append_only_blocks_delete(tmp_path):
    conn = make_db(tmp_path / "t2.sqlite")
    conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
    conn.commit()
    lid = db.insert_ledger(conn, experiment_id=1, agent_id=1, ts=1, tick_index=0, event_type="DECISION",
                           side=None, market_price=100, quantity=0, gross_amount=0, fee=0, tds=0,
                           slippage_cost=0, cash_balance=2000, position_qty=0, reason="x", detail_json=None)
    conn.commit()
    try:
        conn.execute("DELETE FROM ledger WHERE id=?", (lid,))
        conn.commit()
        assert False, "DELETE should have been blocked"
    except sqlite3.IntegrityError:
        pass

def test_buy_then_sell_balance_reconciles_from_ledger_alone(tmp_path):
    """Recompute balance purely from ledger rows (never trust cached agent state)."""
    conn = make_db(tmp_path / "t3.sqlite")
    conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
    conn.commit()

    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    b = PaperBroker(econ, rules, max_frac=0.10)

    cash, pos = 2000.0, 0.0
    buy = b.simulate_buy(ref_price=6400000.0, cash=cash, position_qty=pos, capital_base=2000.0)
    assert buy.accepted
    db.insert_ledger(conn, experiment_id=1, agent_id=1, ts=1, tick_index=0, event_type="FILL", side="BUY",
                     market_price=6400000.0, quantity=buy.quantity, gross_amount=buy.gross_amount,
                     fee=buy.fee, tds=buy.tds, slippage_cost=buy.slippage_cost, cash_balance=buy.cash_after,
                     position_qty=buy.position_after, reason="filled", detail_json=buy.as_detail())
    conn.commit()
    cash, pos = buy.cash_after, buy.position_after

    sell = b.simulate_sell(ref_price=6410000.0, cash=cash, position_qty=pos)
    assert sell.accepted
    db.insert_ledger(conn, experiment_id=1, agent_id=1, ts=2, tick_index=1, event_type="FILL", side="SELL",
                     market_price=6410000.0, quantity=sell.quantity, gross_amount=sell.gross_amount,
                     fee=sell.fee, tds=sell.tds, slippage_cost=sell.slippage_cost, cash_balance=sell.cash_after,
                     position_qty=sell.position_after, reason="filled", detail_json=sell.as_detail())
    conn.commit()

    # Recompute final cash purely by replaying the ledger — no cached/aggregate trust
    rows = conn.execute("SELECT * FROM ledger WHERE agent_id=1 ORDER BY id").fetchall()
    replay_cash = 2000.0
    replay_pos = 0.0
    for r in rows:
        if r["event_type"] != "FILL":
            continue
        if r["side"] == "BUY":
            replay_cash -= (r["gross_amount"] + r["fee"])
            replay_pos += r["quantity"]
        elif r["side"] == "SELL":
            replay_cash += (r["gross_amount"] - r["fee"] - r["tds"])
            replay_pos -= r["quantity"]
    assert abs(replay_cash - sell.cash_after) < 1e-6
    assert abs(replay_pos - sell.position_after) < 1e-9
