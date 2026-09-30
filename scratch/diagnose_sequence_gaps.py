"""Diagnostic script for Phase 10A.5d Sequence Gaps & Disconnects."""

import json
from pathlib import Path
from datetime import datetime, timezone
import duckdb

def diagnose_gaps():
    con = duckdb.connect('data/prediction_market.duckdb', read_only=True)
    
    # 1. Total gaps
    total_gaps = con.execute("SELECT count(*) FROM phase10a5_data_quality WHERE status = 'INVALID_SEQUENCE'").fetchone()[0]
    
    # 2. Gaps by session
    sess_gaps = con.execute("""
        SELECT session_id, count(*) 
        FROM phase10a5_data_quality 
        WHERE status = 'INVALID_SEQUENCE' 
        GROUP BY session_id
    """).fetchall()
    
    # 3. Gaps by component
    comp_gaps = con.execute("""
        SELECT component, count(*) 
        FROM phase10a5_data_quality 
        WHERE status = 'INVALID_SEQUENCE' 
        GROUP BY component
    """).fetchall()

    # 4. Check 20 representative gaps with full context
    sample_gaps = con.execute("""
        SELECT record_id, session_id, market_id, token_id, timestamp, details
        FROM phase10a5_data_quality
        WHERE status = 'INVALID_SEQUENCE'
        ORDER BY timestamp
        LIMIT 25
    """).fetchall()
    
    print("=== SUMMARY OF REPORTED GAPS ===")
    print(f"Total reported sequence gaps: {total_gaps}")
    print("By session:", sess_gaps)
    print("By component:", comp_gaps)
    print()

    # Check disk frames continuity for all sessions
    raw_dir = Path("data/phase10a5_raw")
    print("=== DISK FRAMES CONTINUITY CHECK ===")
    total_disk_frames = 0
    total_disk_gaps = 0
    for sess_dir in sorted(raw_dir.iterdir()):
        if not sess_dir.is_dir():
            continue
        jsonl = sess_dir / "raw_stream.jsonl"
        if not jsonl.exists():
            continue
        seqs = []
        with open(jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    seqs.append(obj["sequence"])
        if not seqs:
            continue
        total_disk_frames += len(seqs)
        gaps_in_sess = 0
        for i in range(len(seqs) - 1):
            if seqs[i+1] != seqs[i] + 1:
                gaps_in_sess += 1
        total_disk_gaps += gaps_in_sess
        print(f"Session {sess_dir.name}: frames={len(seqs)}, min_seq={min(seqs)}, max_seq={max(seqs)}, gaps={gaps_in_sess}")
    
    print(f"Total disk frames across all sessions: {total_disk_frames}")
    print(f"Total disk frame gaps: {total_disk_gaps}")
    print()

    # Trace 20 representative gaps in detail
    print("=== TRACE OF 20 REPRESENTATIVE GAPS ===")
    traces = []
    for idx, (rec_id, s_id, m_id, t_id, ts, details) in enumerate(sample_gaps[:20], 1):
        # Extract expected and observed from details
        # e.g. "Sequence gap detected: expected 2, observed 12 (dropped 10)"
        traces.append({
            "index": idx,
            "record_id": rec_id,
            "session_id": s_id,
            "market_id": m_id[:16] + "..." if m_id else "None",
            "token_id": t_id[:16] + "..." if t_id else "None",
            "timestamp": ts.isoformat(),
            "details": details
        })
        print(f"[{idx:02d}] Session: {s_id} | Token: {t_id[:12]}... | Details: {details}")

    con.close()
    return total_gaps, sess_gaps, traces

if __name__ == "__main__":
    diagnose_gaps()
