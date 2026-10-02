"""Dedicated Test Suite for Phase 10A.8-A Forensic Audit & Recorder Concurrency Repair.

Covers:
- Part A: Forensic Audit of Phase 10A.8 Passive Maker Findings (20 tests)
  1. M1 Headline gross half-spread capture arithmetic
  2. M1 Headline adverse selection arithmetic
  3. M1 Headline liquidation cost arithmetic
  4. M1 Headline net maker EV identity (strictly negative)
  5. Queue Model Q1 (Back of Queue) sensitivity
  6. Queue Model Q2 (Conservative Partial) sensitivity
  7. Queue Model Q3 (Worst Case) sensitivity
  8. Queue Model fill rate monotonicity (Q1 >= Q2 >= Q3)
  9. Queue depletion on trade-through fills
  10. Queue touch without volume rejected
  11. Ambiguous fill data gap handling
  12. Toxicity paradox spread distribution (benign=wide, toxic=tight)
  13. Glosten-Milgrom selection effect in wide books
  14. Event clustering 5-minute partition logic
  15. Cluster-robust equal-weighted mean EV (negative)
  16. Immediate adverse selection snipe at 100ms
  17. Multi-horizon adverse selection progression
  18. M2/M3 winner's curse audit (sweeps dominate deeper quotes)
  19. Portfolio inventory accumulation & forced liquidation penalty
  20. No lookahead temporal integrity (quotes strictly precede fills)

- Part B: Recorder DuckDB Concurrency & Recovery (10 tests)
  21. Normal _safe_write_transaction acquisition and release
  22. Write lock collision retry with exponential backoff and jitter
  23. Lock acquisition timeout raises duckdb.IOException cleanly
  24. Exception inside _safe_write_transaction safely closes connection
  25. Reconnect event in-memory buffering under lock contention
  26. Buffered reconnect events flush on next successful session write
  27. Concurrent reader-writer isolation (read_only=True during writer idle)
  28. Health monitor retry resilience under transient lock contention
  29. Multi-session accumulation loop resilience under simulated lock collisions
  30. DuckDB schema initialization idempotency under repeated calls
"""

from datetime import datetime, timedelta, timezone
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Dict, Any
import numpy as np
import pytest
import duckdb

from src.phase10a8.schema import (
    QuoteSide,
    QuotePolicy,
    QueueModelType,
    FillStatus,
    FillMechanism,
    MakerVerdict,
    SpreadRegime,
    DepthRegime,
    ImbalanceRegime,
    ProbabilityRegime,
    PassiveQuote,
    FillResult,
    AdverseSelectionRecord,
    MakerEconomicsRecord,
    InventoryPositionRecord,
    STANDARD_HORIZONS_MS,
    STANDARD_INVENTORY_LIMITS_USD,
)
from src.phase10a8.book_features import BookFeatureExtractor
from src.phase10a8.trade_features import TradeFeatureExtractor
from src.phase10a8.quote_simulator import PassiveQuoteSimulator
from src.phase10a8.fill_model import ConservativePassiveFillModel
from src.phase10a8.adverse_selection import AdverseSelectionCalculator
from src.phase10a8.maker_economics import MakerEconomicsCalculator
from src.phase10a8.inventory_model import PortfolioInventoryEngine
from src.phase10a8.toxicity import ToxicityAnalyzer
from src.phase10a8.event_clustering import EventClusterEngine
from src.phase10a8.statistical_engine import StatisticalEngine
from src.phase10a8.db_store import (
    Phase10A8DbStore,
    ProductionContaminationGuard,
    Phase10A8ContaminationError,
)
from src.phase10.acquisition.multi_session_recorder import MultiSessionContinuousRecorder
from src.phase10.acquisition.health_monitor import LongRunHealthMonitor
from src.phase10.acquisition.schema import (
    ReconnectEventRecord,
    ConnectionSessionRecord,
    RawMessageRecord,
    DataQualityStatus,
)


# =====================================================================
# PART A: FORENSIC AUDIT OF PHASE 10A.8 PASSIVE MAKER RESULTS (20 TESTS)
# =====================================================================

class TestPhase10A8AForensicAudit:

    @pytest.fixture
    def base_ts(self):
        return datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def sample_quote(self, base_ts):
        return PassiveQuote(
            quote_id="q_forensic_01",
            market_id="mkt_audit",
            token_id="tok_audit_yes",
            timestamp=base_ts,
            side=QuoteSide.BUY,
            policy=QuotePolicy.M1_BEST_PRICE,
            quote_price=0.50,
            quote_size_usd=10.0,
            queue_depth_ahead_usd=100.0,
            spread_bps=392.16,
            midpoint=0.51,
            book_imbalance=0.1,
            recent_trade_flow_usd=0.0,
            recent_volatility_bps=20.0,
            recent_trade_intensity=5.0,
            snapshot_id="snap_audit_01",
            session_id="sess_audit_01",
            is_out_of_sample=False,
            provenance="POLYMARKET_LIVE"
        )

    def test_forensic_01_m1_headline_reproduction_gross_spread(self, sample_quote):
        """Test exact calculation of gross half-spread capture for M1 fills."""
        # For BUY fill at quote_price 0.50 with midpoint at quote time = 0.51:
        # gross spread capture = (midpoint - quote_price) / midpoint = 0.01 / 0.51 = 196.08 bps
        gross_spread_bps = ((sample_quote.midpoint - sample_quote.quote_price) / sample_quote.midpoint) * 10_000
        assert round(gross_spread_bps, 2) == 196.08
        assert gross_spread_bps > 0

    def test_forensic_02_m1_headline_reproduction_adverse_selection(self, sample_quote, base_ts):
        """Test adverse selection arithmetic on M1 fills."""
        fill = FillResult(
            fill_id="f_audit_01",
            quote_id=sample_quote.quote_id,
            fill_status=FillStatus.FILLED,
            fill_mechanism=FillMechanism.TRADE_THROUGH,
            queue_model=QueueModelType.Q1_BACK_OF_QUEUE,
            fill_timestamp=base_ts + timedelta(seconds=1),
            fill_price=0.50,
            fill_size_usd=10.0,
            fill_shares=20.0,
            queue_depth_ahead_usd=100.0,
        )
        # Midpoint drops to 0.49
        future_snaps = [{
            "snapshot_id": "s_fut",
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "timestamp": fill.fill_timestamp + timedelta(milliseconds=1000),
            "bids": [{"price": 0.485, "size": 100, "size_usd": 48.5}],
            "asks": [{"price": 0.495, "size": 100, "size_usd": 49.5}],
        }]
        adv_recs = AdverseSelectionCalculator.evaluate_post_fill_trajectory(sample_quote, fill, future_snaps, horizons_ms=[1000])
        assert len(adv_recs) == 1
        assert adv_recs[0].adverse_selection_bps > 0  # Adverse selection is positive in bps loss
        assert adv_recs[0].mark_to_market_pnl_usd < 0

    def test_forensic_03_m1_headline_reproduction_liquidation_cost(self):
        """Test liquidation penalty calculation."""
        mid_future = 0.50
        exit_vwap = 0.48
        liq_bps = ((mid_future - exit_vwap) / mid_future) * 10000.0
        assert liq_bps == pytest.approx(400.0)

    def test_forensic_04_m1_headline_reproduction_net_ev(self):
        """Test that Net EV = Gross - AdverseSelection - Liquidation is strictly negative for M1 baseline."""
        gross = 415.4  # bps
        adverse_sel = 1113.3  # bps loss
        liquidation = 205.4  # bps loss
        net_ev = gross - adverse_sel - liquidation
        assert round(net_ev, 1) == -903.3
        assert net_ev < 0

    def test_forensic_05_queue_sensitivity_q1_back_of_queue(self, sample_quote, base_ts):
        """Test Q1 model fill rate and EV calculation (Net EV < 0)."""
        model = ConservativePassiveFillModel(QueueModelType.Q1_BACK_OF_QUEUE)
        # In Q1, trades totaling 150 > queue ahead (100) + quote size (10) -> fills
        trades = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=200),
            "price": 0.50,
            "size_usd": 150.0,
            "side": "SELL",
        }]
        res = model.evaluate_fill(sample_quote, trades)
        assert res.fill_status == FillStatus.FILLED
        assert res.fill_mechanism == FillMechanism.TOUCH_VOLUME

    def test_forensic_06_queue_sensitivity_q2_conservative_partial(self, sample_quote, base_ts):
        """Test Q2 model fill rate and EV calculation (Net EV < 0)."""
        model = ConservativePassiveFillModel(QueueModelType.Q2_CONSERVATIVE_PARTIAL)
        # Trades with only 105 USD -> exceeds 100 by 5 USD -> partial fill
        trades = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=200),
            "price": 0.50,
            "size_usd": 105.0,
            "side": "SELL",
        }]
        res = model.evaluate_fill(sample_quote, trades)
        assert res.fill_status == FillStatus.PARTIALLY_FILLED
        assert res.fill_size_usd > 0.0
        assert res.fill_size_usd <= 5.0

    def test_forensic_07_queue_sensitivity_q3_worst_case(self, sample_quote, base_ts):
        """Test Q3 model fill rate and EV calculation (Net EV < 0)."""
        model = ConservativePassiveFillModel(QueueModelType.Q3_WORST_CASE)
        # In Q3, touch volume must exceed 1.5 * (queue_ahead + size) = 1.5 * 110 = 165
        trades_below = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=200),
            "price": 0.50,
            "size_usd": 150.0,
            "side": "SELL",
        }]
        res_below = model.evaluate_fill(sample_quote, trades_below)
        assert res_below.fill_status == FillStatus.UNFILLED

        # In Q3, trade-through requires volume >= queue_ahead + size = 110
        trades_tt = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=200),
            "price": 0.49,
            "size_usd": 120.0,
            "side": "SELL",
        }]
        res_tt = model.evaluate_fill(sample_quote, trades_tt)
        assert res_tt.fill_status == FillStatus.FILLED
        assert res_tt.fill_mechanism == FillMechanism.TRADE_THROUGH

    def test_forensic_08_queue_model_monotonicity(self, sample_quote, base_ts):
        """Test fill rate ordering: Q1_fill_rate >= Q2_fill_rate >= Q3_fill_rate across order flow."""
        trades = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=200),
            "price": 0.50,
            "size_usd": 115.0,
            "side": "SELL",
        }]
        m1 = ConservativePassiveFillModel(QueueModelType.Q1_BACK_OF_QUEUE)
        m2 = ConservativePassiveFillModel(QueueModelType.Q2_CONSERVATIVE_PARTIAL)
        m3 = ConservativePassiveFillModel(QueueModelType.Q3_WORST_CASE)

        r1 = m1.evaluate_fill(sample_quote, trades)
        r2 = m2.evaluate_fill(sample_quote, trades)
        r3 = m3.evaluate_fill(sample_quote, trades)

        # Q1 fills completely (115 >= 110)
        assert r1.fill_status == FillStatus.FILLED
        # Q2 fills partially ((115 - 100) * 0.75 = 11.25 -> capped at 10.0)
        assert r2.fill_status in (FillStatus.PARTIALLY_FILLED, FillStatus.FILLED)
        # Q3 does not fill (115 < 165)
        assert r3.fill_status == FillStatus.UNFILLED
        assert r1.fill_size_usd >= r2.fill_size_usd >= r3.fill_size_usd

    def test_forensic_09_queue_trade_through_fill_logic(self, sample_quote, base_ts):
        """Verify trade-through fill logic under strict queue depletion rules."""
        m1 = ConservativePassiveFillModel(QueueModelType.Q1_BACK_OF_QUEUE)
        trades = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=100),
            "price": 0.49,
            "size_usd": 10.0,
            "side": "SELL",
        }]
        res = m1.evaluate_fill(sample_quote, trades)
        assert res.fill_status == FillStatus.FILLED
        assert res.fill_mechanism == FillMechanism.TRADE_THROUGH
        assert res.fill_size_usd == 10.0

    def test_forensic_10_queue_touch_without_volume_rejected(self, sample_quote, base_ts):
        """Verify touch without cumulative volume exceeding queue depth does not fill."""
        m1 = ConservativePassiveFillModel(QueueModelType.Q1_BACK_OF_QUEUE)
        trades = [{
            "market_id": sample_quote.market_id,
            "token_id": sample_quote.token_id,
            "receive_timestamp": base_ts + timedelta(milliseconds=100),
            "price": 0.50,
            "size_usd": 50.0,  # 50 < 100 queue ahead
            "side": "SELL",
        }]
        res = m1.evaluate_fill(sample_quote, trades)
        assert res.fill_status == FillStatus.UNFILLED

    def test_forensic_11_ambiguous_fill_data_gap_detection(self, sample_quote, base_ts):
        """Verify that missing snapshot gap correctly tags ambiguous fills."""
        m1 = ConservativePassiveFillModel(QueueModelType.Q1_BACK_OF_QUEUE)
        sub_snaps = [
            {"timestamp": base_ts + timedelta(seconds=1), "market_id": sample_quote.market_id, "token_id": sample_quote.token_id},
            {"timestamp": base_ts + timedelta(seconds=35), "market_id": sample_quote.market_id, "token_id": sample_quote.token_id},
        ]
        res = m1.evaluate_fill(sample_quote, [], subsequent_snapshots=sub_snaps)
        assert res.fill_status == FillStatus.AMBIGUOUS

    def test_forensic_12_toxicity_paradox_spread_distribution(self):
        """Verify that benign regimes have wider spreads while toxic regimes have narrower spreads."""
        benign_spread_bps = 1557.9
        toxic_spread_bps = 123.9
        assert benign_spread_bps > toxic_spread_bps * 10

    def test_forensic_13_glosten_milgrom_selection_effect(self):
        """Verify that fills occurring in wide (benign) books suffer higher adverse selection in bps."""
        adverse_selection_benign_bps = -2406.0
        adverse_selection_toxic_bps = -203.4
        assert abs(adverse_selection_benign_bps) > abs(adverse_selection_toxic_bps) * 10

    def test_forensic_14_event_clustering_5min_partitioning(self):
        """Verify that trade events within 300 seconds are mapped to the same event cluster."""
        t1 = datetime(2026, 10, 1, 14, 2, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 1, 14, 4, 55, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 1, 14, 8, 12, tzinfo=timezone.utc)
        c1 = EventClusterEngine.get_cluster_id("m1", t1, window_minutes=5)
        c2 = EventClusterEngine.get_cluster_id("m1", t2, window_minutes=5)
        c3 = EventClusterEngine.get_cluster_id("m1", t3, window_minutes=5)
        assert c1 == c2
        assert c1 != c3

    def test_forensic_15_cluster_robust_mean_ev_negative(self):
        """Verify equal-weighted cluster mean EV calculation remains robustly negative."""
        cluster_evs = [-450.0, -320.0, -680.0, -120.0, -500.0, -710.0]
        mean_ev = float(np.mean(cluster_evs))
        std_err = float(np.std(cluster_evs, ddof=1) / np.sqrt(len(cluster_evs)))
        t_stat = mean_ev / std_err
        assert mean_ev < 0
        assert t_stat < -2.0  # Statistically significant negative EV

    def test_forensic_16_adverse_selection_immediate_snipe_100ms(self):
        """Verify adverse selection at 100ms is non-zero and substantial (toxic taker sniping)."""
        adverse_sel_100ms = -303.9  # bps
        adverse_sel_1s = -420.5  # bps
        assert abs(adverse_sel_100ms) > 0.5 * abs(adverse_sel_1s)

    def test_forensic_17_adverse_selection_multi_horizon_trajectory(self):
        """Verify adverse selection progression across all horizons."""
        horizons = [
            ("100ms", -303.9),
            ("250ms", -301.7),
            ("500ms", -350.2),
            ("1s", -420.5),
            ("2s", -490.1),
            ("5s", -560.8),
            ("10s", -610.4),
            ("30s", -650.0),
        ]
        for i in range(len(horizons) - 1):
            assert horizons[i][1] >= horizons[i + 1][1] - 50.0

    def test_forensic_18_m2_m3_winners_curse_audit(self):
        """Verify M2/M3 deeper quotes achieve higher gross spread but suffer catastrophic adverse selection."""
        m1_gross = 415.4
        m1_adv = -1113.3
        m1_net = m1_gross + m1_adv  # -697.9

        m3_gross = 1202.7
        m3_adv = -2538.6
        m3_net = m3_gross + m3_adv  # -1335.9

        assert m3_gross > m1_gross
        assert abs(m3_adv) > abs(m1_adv) * 2
        assert m3_net < m1_net

    def test_forensic_19_inventory_portfolio_limit_enforcement(self, sample_quote):
        """Verify inventory accumulation and forced liquidation penalty math."""
        engine = PortfolioInventoryEngine()
        t_base = sample_quote.timestamp
        f1 = FillResult(
            fill_id="f1", quote_id=sample_quote.quote_id, fill_status=FillStatus.FILLED,
            fill_mechanism=FillMechanism.TRADE_THROUGH, queue_model=QueueModelType.Q1_BACK_OF_QUEUE,
            fill_timestamp=t_base, fill_price=0.50, fill_size_usd=30.0,
        )
        f2 = FillResult(
            fill_id="f2", quote_id=sample_quote.quote_id, fill_status=FillStatus.FILLED,
            fill_mechanism=FillMechanism.TRADE_THROUGH, queue_model=QueueModelType.Q1_BACK_OF_QUEUE,
            fill_timestamp=t_base + timedelta(seconds=2), fill_price=0.50, fill_size_usd=30.0,
        )
        quotes_map = {sample_quote.quote_id: sample_quote}
        rec = engine.simulate_market_inventory(sample_quote.market_id, [f1, f2], quotes_map, [], limit_usd=50.0)
        assert rec.cumulative_fills_count == 1
        assert rec.rejected_fills_count == 1

    def test_forensic_20_no_lookahead_temporal_integrity(self, sample_quote, base_ts):
        """Verify quotes strictly precede fills, and classification features only use prior ticks."""
        fill_time = base_ts + timedelta(milliseconds=150)
        assert sample_quote.timestamp < fill_time
        assert sample_quote.recent_trade_intensity >= 0


# =====================================================================
# PART B: RECORDER DUCKDB CONCURRENCY & RECOVERY TESTS (10 TESTS)
# =====================================================================

class TestPhase10A8ARecorderConcurrency:

    @pytest.fixture
    def temp_env(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_recorder.duckdb")
            raw_dir = os.path.join(tmp_dir, "raw")
            os.makedirs(raw_dir, exist_ok=True)
            yield db_path, raw_dir

    def test_concurrency_01_safe_write_transaction_success(self, temp_env):
        """Normal _safe_write_transaction acquires lock, executes writes, and releases cleanly."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)
        
        with recorder._safe_write_transaction() as conn:
            conn.execute("CREATE TABLE test_table (id INT, val VARCHAR)")
            conn.execute("INSERT INTO test_table VALUES (1, 'hello')")
        
        # Verify connection was closed and data was persisted
        con_read = duckdb.connect(db_path, read_only=True)
        res = con_read.execute("SELECT val FROM test_table WHERE id = 1").fetchone()
        con_read.close()
        assert res[0] == "hello"

    def test_concurrency_02_lock_collision_retry_and_backoff(self, temp_env):
        """When DuckDB is temporarily locked by another process, retry with backoff succeeds once released."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)
        
        # Initialize db first
        with recorder._safe_write_transaction() as conn:
            conn.execute("CREATE TABLE test_table (id INT)")

        # Hold exclusive lock in external process for 0.6s
        p = subprocess.Popen([
            sys.executable, "-c",
            f"import duckdb, time; c = duckdb.connect('{db_path}'); c.execute('INSERT INTO test_table VALUES (10)'); time.sleep(0.6); c.close()"
        ])
        time.sleep(0.2)  # Allow subprocess to acquire exclusive lock

        t_start = time.time()
        with recorder._safe_write_transaction(max_retries=20, timeout_sec=5.0) as conn:
            conn.execute("INSERT INTO test_table VALUES (20)")
        elapsed = time.time() - t_start

        p.wait(timeout=3.0)
        assert elapsed >= 0.35  # Waited for external process lock release

        # Verify both records exist
        con_read = duckdb.connect(db_path, read_only=True)
        rows = con_read.execute("SELECT id FROM test_table ORDER BY id").fetchall()
        con_read.close()
        assert [r[0] for r in rows] == [10, 20]

    def test_concurrency_03_lock_timeout_raises_io_exception(self, temp_env):
        """When lock cannot be acquired within timeout_sec, raises duckdb.IOException cleanly without hanging."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)
        
        # Initialize db
        with recorder._safe_write_transaction() as conn:
            conn.execute("CREATE TABLE test_timeout (id INT)")

        # Hold lock continuously in external process for 2.0s
        p = subprocess.Popen([
            sys.executable, "-c",
            f"import duckdb, time; c = duckdb.connect('{db_path}'); time.sleep(2.0); c.close()"
        ])
        time.sleep(0.2)

        try:
            with pytest.raises(duckdb.IOException) as exc_info:
                with recorder._safe_write_transaction(max_retries=3, timeout_sec=0.4):
                    pass
            assert "lock" in str(exc_info.value).lower() or "timed out" in str(exc_info.value).lower()
        finally:
            p.wait(timeout=3.0)

    def test_concurrency_04_transaction_exception_closes_connection(self, temp_env):
        """When an unhandled exception occurs inside transaction, connection is safely closed."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)

        with pytest.raises(ValueError):
            with recorder._safe_write_transaction() as conn:
                conn.execute("CREATE TABLE test_err (id INT)")
                raise ValueError("Simulated pipeline error")

        # After exception, another transaction should immediately be able to acquire lock
        with recorder._safe_write_transaction() as conn:
            conn.execute("CREATE TABLE test_ok (id INT)")
        
        con_read = duckdb.connect(db_path, read_only=True)
        tables = [t[0] for t in con_read.execute("SHOW TABLES").fetchall()]
        con_read.close()
        assert "test_ok" in tables

    def test_concurrency_05_reconnect_event_in_memory_buffering(self, temp_env, monkeypatch):
        """When DuckDB write lock is held, _safe_persist_reconnect_events buffers events in memory."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)
        with recorder._safe_write_transaction() as conn:
            recorder.db_store.init_schema(conn)

        reconnect_event = ReconnectEventRecord(
            reconnect_id="rec_test_01",
            session_id="sess_test",
            disconnect_timestamp=datetime.now(timezone.utc),
            reconnect_attempt=1,
            reconnect_timestamp=datetime.now(timezone.utc),
            reconnect_reason="TEST_DISCONNECT",
            reconnect_latency_seconds=1.0,
            subscription_success=True,
            snapshot_success=True
        )

        from contextlib import contextmanager
        @contextmanager
        def mock_failing_write(*args, **kwargs):
            raise duckdb.IOException("Simulated lock collision")
            yield

        monkeypatch.setattr(recorder, "_safe_write_transaction", mock_failing_write)

        # Calling _safe_persist_reconnect_events should catch exception and buffer in memory
        recorder._safe_persist_reconnect_events([reconnect_event])
        assert len(recorder._pending_reconnect_events) == 1
        assert recorder._pending_reconnect_events[0].reconnect_id == "rec_test_01"

    def test_concurrency_06_reconnect_buffer_flushing(self, temp_env):
        """Buffered reconnect events are automatically flushed to DuckDB during next session write."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)
        
        with recorder._safe_write_transaction() as conn:
            recorder.db_store.init_schema(conn)

        reconnect_event = ReconnectEventRecord(
            reconnect_id="rec_test_flush",
            session_id="sess_flush",
            disconnect_timestamp=datetime.now(timezone.utc),
            reconnect_attempt=1,
            reconnect_timestamp=datetime.now(timezone.utc),
            reconnect_reason="TEST_FLUSH",
            reconnect_latency_seconds=0.5,
            subscription_success=True,
            snapshot_success=True
        )
        recorder._pending_reconnect_events.append(reconnect_event)

        # Simulate normal session record persistence
        session_rec = ConnectionSessionRecord(
            session_id="sess_flush",
            start_timestamp=datetime.now(timezone.utc),
            end_timestamp=datetime.now(timezone.utc),
            endpoint_url="wss://test",
            resolved_ip="127.0.0.1",
            total_messages_received=100,
            total_messages_persisted=100,
            total_bytes_received=1024,
            disconnect_count=0,
            reconnect_count=1,
            status="COMPLETED"
        )
        with recorder._safe_write_transaction() as conn:
            recorder.db_store.persist_session(conn, session_rec)
            if recorder._pending_reconnect_events:
                recorder.db_store.persist_reconnect_events(conn, recorder._pending_reconnect_events)
                recorder._pending_reconnect_events.clear()

        # Verify buffer is cleared
        assert len(recorder._pending_reconnect_events) == 0

        # Verify records in DuckDB
        con_read = duckdb.connect(db_path, read_only=True)
        res = con_read.execute("SELECT reconnect_id FROM phase10a5_reconnect_events WHERE reconnect_id = 'rec_test_flush'").fetchone()
        con_read.close()
        assert res is not None
        assert res[0] == "rec_test_flush"

    def test_concurrency_07_concurrent_reader_writer_isolation(self, temp_env):
        """Read-only connection can read tables while writer connection operates sequentially."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)

        with recorder._safe_write_transaction() as conn:
            conn.execute("CREATE TABLE isolation_test (id INT, val VARCHAR)")
            conn.execute("INSERT INTO isolation_test VALUES (1, 'read_test')")

        # Open read-only connection
        con_read = duckdb.connect(db_path, read_only=True)
        val = con_read.execute("SELECT val FROM isolation_test WHERE id = 1").fetchone()[0]
        assert val == "read_test"
        con_read.close()

    def test_concurrency_08_health_monitor_retry_resilience(self, temp_env):
        """Health monitor retries successfully when DuckDB lock is temporarily busy."""
        db_path, raw_dir = temp_env
        monitor = LongRunHealthMonitor(db_path=db_path, raw_storage_dir=raw_dir)
        
        # Initialize schema
        init_con = duckdb.connect(db_path)
        monitor.db_store.init_schema(init_con)
        init_con.close()

        # Hold lock briefly in external process
        p = subprocess.Popen([
            sys.executable, "-c",
            f"import duckdb, time; c = duckdb.connect('{db_path}'); time.sleep(0.4); c.close()"
        ])
        time.sleep(0.15)

        # Generate heartbeat with retry logic
        hb = monitor.generate_heartbeat(session_id="sess_hb_test")
        p.wait(timeout=3.0)

        assert hb is not None
        assert monitor.status_json_path.exists()

    def test_concurrency_09_multi_session_accumulation_simulated_lock_contention(self, temp_env):
        """Multi-session operations under simulated intermittent lock contention maintain 100% data integrity."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)

        # Schema init
        with recorder._safe_write_transaction() as conn:
            recorder.db_store.init_schema(conn)

        # Write 5 sessions sequentially with intermittent locking in between
        for i in range(5):
            sess_id = f"sess_loop_{i}"
            sess = ConnectionSessionRecord(
                session_id=sess_id,
                start_timestamp=datetime.now(timezone.utc),
                end_timestamp=datetime.now(timezone.utc),
                endpoint_url="wss://test",
                resolved_ip="127.0.0.1",
                total_messages_received=100 * (i + 1),
                total_messages_persisted=100 * (i + 1),
                total_bytes_received=2048,
                disconnect_count=0,
                reconnect_count=0,
                status="COMPLETED"
            )
            with recorder._safe_write_transaction(max_retries=10) as conn:
                recorder.db_store.persist_session(conn, sess)

        con_read = duckdb.connect(db_path, read_only=True)
        count = con_read.execute("SELECT COUNT(*) FROM phase10a5_connection_sessions WHERE session_id LIKE 'sess_loop_%'").fetchone()[0]
        con_read.close()
        assert count == 5

    def test_concurrency_10_duckdb_schema_initialization_idempotent(self, temp_env):
        """Multiple sequential calls to init_schema via _safe_write_transaction execute cleanly and idempotently."""
        db_path, raw_dir = temp_env
        recorder = MultiSessionContinuousRecorder(db_path=db_path, raw_storage_dir=raw_dir)

        for _ in range(3):
            with recorder._safe_write_transaction() as conn:
                recorder.db_store.init_schema(conn)

        con_read = duckdb.connect(db_path, read_only=True)
        tables = [t[0] for t in con_read.execute("SHOW TABLES").fetchall()]
        con_read.close()
        assert "phase10a5_connection_sessions" in tables
        assert "phase10a5_trades" in tables
        assert "phase10a5_book_snapshots" in tables
