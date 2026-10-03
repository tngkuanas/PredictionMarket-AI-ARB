"""PyTest Configuration for PredictionMarketModel Test Suite.

Provides transparent read-only connection fallbacks when the live Polymarket
recorder daemon holds an exclusive write lock on data/prediction_market.duckdb.
"""

import os
import duckdb
import pytest

_orig_duckdb_connect = duckdb.connect


def _safe_duckdb_connect(database=":memory:", *args, **kwargs):
    try:
        return _orig_duckdb_connect(database, *args, **kwargs)
    except Exception as e:
        err_msg = str(e).lower()
        if ("lock" in err_msg or "locked" in err_msg) and "prediction_market.duckdb" in str(database):
            ro_path = "data/prediction_market_readonly.duckdb"
            if os.path.exists(ro_path):
                return _orig_duckdb_connect(ro_path, *args, **kwargs)
        raise e



@pytest.fixture(autouse=True, scope="session")
def configure_safe_duckdb_concurrency():
    """Patches duckdb.connect to seamlessly fallback to read-only snapshot if live DB is locked."""
    duckdb.connect = _safe_duckdb_connect
    yield
    duckdb.connect = _orig_duckdb_connect
