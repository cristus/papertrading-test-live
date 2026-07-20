"""Dashboard read-only enforcement."""
import os, sys, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.db import init_db, connect_readonly

def test_readonly_connection_rejects_writes(tmp_path):
    p = str(tmp_path / "ro.sqlite")
    init_db(p).close()
    conn = connect_readonly(p)
    try:
        conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
        conn.commit()
        assert False, "write should have been rejected on a read-only connection"
    except sqlite3.OperationalError as e:
        assert "readonly" in str(e).lower()
    finally:
        conn.close()

def test_dashboard_app_has_no_write_routes():
    """Static check: the Flask app source contains no INSERT/UPDATE/DELETE/execute-with-write verbs."""
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "app.py")
    with open(path) as f:
        src = f.read().upper()
    for verb in ["INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE", "ALTER TABLE"]:
        assert verb not in src, f"dashboard app.py must not contain '{verb}'"

def test_dashboard_before_request_blocks_non_get():
    """The Flask app registers a before_request guard that 405s any non-GET/HEAD/OPTIONS."""
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "app.py")
    with open(path) as f:
        src = f.read()
    assert "enforce_read_only" in src
    assert "abort(405)" in src

def test_dashboard_uses_connect_readonly_everywhere():
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "app.py")
    with open(path) as f:
        src = f.read()
    assert "connect_readonly" in src
    assert "def connect(" not in src  # dashboard never imports the writable connect()
