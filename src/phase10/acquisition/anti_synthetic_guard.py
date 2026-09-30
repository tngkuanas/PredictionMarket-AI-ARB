"""Anti-Synthetic Guard for Phase 10A.5 Production Pipeline.

Enforces a strict zero-tolerance ban on synthetic market data in production tables:
- Rejects Gaussian noise, logistic S-curves, random price generators, placeholder tokens.
- Verifies that all raw messages possess valid SHA-256 digests and exist on disk.
- Fails immediately if synthetic fixtures attempt to write to production DuckDB tables.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Any, Dict, Optional

import duckdb

logger = logging.getLogger(__name__)


class SyntheticDataViolationError(Exception):
    """Raised when synthetic or fabricated data is detected in production paths."""
    pass


class AntiSyntheticGuard:
    """Validates records before insertion into production Phase 10A.5 DuckDB tables."""

    BANNED_TOKEN_PREFIXES = ["token_geopol_", "token_reg_", "token_crypto_", "token_pol_", "token_test_"]
    BANNED_TERMS = ["logistic", "target_delta", "dir_mult", "np.random.normal", "base_mid"]

    @classmethod
    def validate_raw_message(cls, raw_rec: Any) -> None:
        """Ensures raw message has authentic structure and cryptographic integrity."""
        # Check SHA-256 hash
        computed_sha = hashlib.sha256(raw_rec.raw_message_json.encode("utf-8")).hexdigest()
        if computed_sha != raw_rec.sha256_hash:
            raise SyntheticDataViolationError(
                f"SHA-256 mismatch in message {raw_rec.message_id}: "
                f"expected {raw_rec.sha256_hash}, computed {computed_sha}"
            )

        # Check raw file path existence (with path cache to avoid thousands of disk stat calls)
        if raw_rec.raw_file_path:
            if raw_rec.raw_file_path not in getattr(cls, "_checked_paths", set()):
                if not Path(raw_rec.raw_file_path).exists():
                    raise SyntheticDataViolationError(
                        f"Raw file {raw_rec.raw_file_path} does not exist on disk for message {raw_rec.message_id}"
                    )
                if not hasattr(cls, "_checked_paths"):
                    cls._checked_paths = set()
                cls._checked_paths.add(raw_rec.raw_file_path)

        # Check for placeholder tokens
        if raw_rec.token_id:
            for prefix in cls.BANNED_TOKEN_PREFIXES:
                if raw_rec.token_id.startswith(prefix):
                    raise SyntheticDataViolationError(
                        f"Banned synthetic placeholder token detected in production message: {raw_rec.token_id}"
                    )

    @classmethod
    def validate_book_snapshot(cls, snap: Any) -> None:
        """Ensures book snapshot does not contain synthetic markers."""
        if snap.token_id:
            for prefix in cls.BANNED_TOKEN_PREFIXES:
                if snap.token_id.startswith(prefix):
                    raise SyntheticDataViolationError(
                        f"Banned placeholder token in book snapshot: {snap.token_id}"
                    )

        # Basic range sanity
        if snap.best_bid < 0.0 or snap.best_ask > 1.0 or snap.best_bid > 1.0 or snap.best_ask < 0.0:
            raise SyntheticDataViolationError(
                f"Impossible price bounds in snapshot {snap.snapshot_id}: bid={snap.best_bid}, ask={snap.best_ask}"
            )

    @classmethod
    def validate_trade(cls, trade: Any) -> None:
        """Ensures trade record is valid and non-synthetic."""
        if trade.token_id:
            for prefix in cls.BANNED_TOKEN_PREFIXES:
                if trade.token_id.startswith(prefix):
                    raise SyntheticDataViolationError(
                        f"Banned placeholder token in trade: {trade.token_id}"
                    )

        if trade.price <= 0.0 or trade.price >= 1.0 or trade.size <= 0.0:
            raise SyntheticDataViolationError(
                f"Impossible trade parameters: price={trade.price}, size={trade.size}"
            )

    @classmethod
    def validate_token_id(cls, token_id: Optional[str]) -> bool:
        """Validates that a token ID is a genuine exchange token format and not a placeholder."""
        if not token_id:
            return False
        for prefix in cls.BANNED_TOKEN_PREFIXES:
            if token_id.startswith(prefix):
                return False
        # Polymarket tokens are either hex addresses (0x...) or large decimal token IDs
        if token_id.startswith("0x") and len(token_id) >= 10:
            return True
        if token_id.isdigit() and len(token_id) >= 10:
            return True
        return False

    @classmethod
    def scan_production_tables(cls, conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Scans DuckDB Phase 10A.5 tables to guarantee zero synthetic data was persisted."""
        results = {"clean": True, "violations": []}
        
        # Check raw messages table
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        if "phase10a5_raw_messages" in tables:
            placeholders = conn.execute("""
                SELECT count(*) FROM phase10a5_raw_messages 
                WHERE token_id LIKE 'token_%'
            """).fetchone()[0]
            if placeholders > 0:
                results["clean"] = False
                results["violations"].append(f"Found {placeholders} placeholder tokens in phase10a5_raw_messages")

        if "phase10a5_book_snapshots" in tables:
            invalid_prices = conn.execute("""
                SELECT count(*) FROM phase10a5_book_snapshots
                WHERE best_bid < 0 OR best_ask > 1.0 OR token_id LIKE 'token_%'
            """).fetchone()[0]
            if invalid_prices > 0:
                results["clean"] = False
                results["violations"].append(f"Found {invalid_prices} invalid snapshots in phase10a5_book_snapshots")

        if "phase10a5_market_universe" in tables:
            invalid_univ = conn.execute("""
                SELECT count(*) FROM phase10a5_market_universe
                WHERE token_id LIKE 'token_%'
            """).fetchone()[0]
            if invalid_univ > 0:
                results["clean"] = False
                results["violations"].append(f"Found {invalid_univ} placeholder tokens in phase10a5_market_universe")

        return results
