"""Death and reproduction threshold detection, including proportional scaling per tier."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.agent import AgentState, LifecycleChecker

def make_checker():
    return LifecycleChecker(death_fraction=0.40, reproduction_fraction=2.00, child_fraction=0.50)

def test_death_threshold_proportional_across_tiers():
    lc = make_checker()
    assert lc.death_threshold(2000) == 800.0
    assert lc.death_threshold(8000) == 3200.0
    assert lc.death_threshold(20000) == 8000.0
    # ratio must be identical across tiers (proportional scaling)
    assert lc.death_threshold(8000) / 8000 == lc.death_threshold(2000) / 2000 == lc.death_threshold(20000) / 20000

def test_reproduction_threshold_proportional_across_tiers():
    lc = make_checker()
    assert lc.reproduction_threshold(2000) == 4000.0
    assert lc.reproduction_threshold(8000) == 16000.0
    assert lc.reproduction_threshold(20000) == 40000.0

def test_death_detected_at_or_below_threshold():
    lc = make_checker()
    a = AgentState(id=1, experiment_id=1, cohort="tier_2k", starting_capital=2000,
                   cash=2000, position_qty=0, avg_entry_price=None)
    assert lc.check_death(a, 900) is None
    assert lc.check_death(a, 800) is not None   # exactly at threshold -> death
    assert lc.check_death(a, 799) is not None

def test_reproduction_signal_logged_once_only():
    lc = make_checker()
    a = AgentState(id=1, experiment_id=1, cohort="tier_2k", starting_capital=2000,
                   cash=2000, position_qty=0, avg_entry_price=None)
    r1 = lc.check_reproduction(a, 4200)
    assert r1 is not None
    assert "would spawn child with capital 1000.00" in r1
    a.reproduced_logged = True
    r2 = lc.check_reproduction(a, 4300)
    assert r2 is None  # already logged, must not re-log

def test_dead_agent_never_reproduces():
    lc = make_checker()
    a = AgentState(id=1, experiment_id=1, cohort="tier_2k", starting_capital=2000,
                   cash=2000, position_qty=0, avg_entry_price=None, alive=False)
    assert lc.check_reproduction(a, 5000) is None
    assert lc.check_death(a, 100) is None

def test_child_capital_is_half_of_parent_starting_capital():
    lc = make_checker()
    assert lc.child_capital(2000) == 1000.0
    assert lc.child_capital(8000) == 4000.0
    assert lc.child_capital(20000) == 10000.0
