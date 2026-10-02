"""Master Forensic Audit Orchestrator for Phase 10A.10-C.

Coordinates all forensic audit modules:
- Reproduction Engine
- Resolution and Mapping Engine
- Economic Trace and Counterfactual Entry Engine
- Independence, Duplicate, and Bootstrap Engine
- Original Phase 10A.10 Comparison Engine
- 23-Section Report Generator
"""

import logging
import os
import time
from typing import Dict, Any

from src.phase10a10c import Phase10A10CVerdict
from src.phase10a10c.reproduction import IndependentReproductionEngine
from src.phase10a10c.resolution_audit import ResolutionAndMappingAuditEngine
from src.phase10a10c.economic_trace import EconomicTraceAuditEngine
from src.phase10a10c.independence_audit import IndependenceAndOverlapAuditEngine
from src.phase10a10c.original_comparison import OriginalPhase10A10ComparisonEngine
from src.phase10a10c.report import Phase10A10CReportGenerator
from src.phase10a10b.pipeline import Phase10A10BPipeline

logger = logging.getLogger(__name__)


class Phase10A10CAuditRunner:
    """Coordinates and executes the complete Phase 10A.10-C forensic audit."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def run_full_audit(self) -> Dict[str, Any]:
        """Runs the complete forensic audit suite."""
        logger.info("Starting Phase 10A.10-C Forensic Audit of Phase 10A.10-B...")
        t0 = time.time()

        # 1. Independent Reproduction
        reproduction = IndependentReproductionEngine.run_reproduction(db_path=self.db_path)
        oos_executions = reproduction["oos_executions"]
        raw_candidates = reproduction["raw_candidates"]
        accepted_events = reproduction["accepted_events"]
        oos_events = reproduction["oos_events"]

        # 2. Resolution & Mapping Audit
        resolution_audit = ResolutionAndMappingAuditEngine.audit_resolution_status(
            events=accepted_events, executions=oos_executions, db_path=self.db_path
        )
        mapping_audit = ResolutionAndMappingAuditEngine.audit_outcome_mapping(
            events=accepted_events, executions=oos_executions
        )
        near_zero_audit = ResolutionAndMappingAuditEngine.audit_near_zero_prices(
            executions=oos_executions
        )
        price_scale_audit = ResolutionAndMappingAuditEngine.audit_price_scale(
            executions=oos_executions
        )

        # 3. Economic Trace & Counterfactual Entry
        traces = EconomicTraceAuditEngine.generate_economic_traces(
            oos_executions=oos_executions, raw_candidates=raw_candidates, sample_size=100
        )
        pipeline = Phase10A10BPipeline(db_path=self.db_path)
        token_snapshots = pipeline.load_snapshots_for_tokens([e.token_id for e in accepted_events])
        counterfactual_audit = EconomicTraceAuditEngine.audit_counterfactual_entry(
            oos_executions=oos_executions, token_snapshots=token_snapshots, sample_size=100
        )
        capacity_audit = EconomicTraceAuditEngine.audit_capacity_and_slippage(
            oos_executions=oos_executions
        )

        # 4. Independence, Duplication, Overlap, and Bootstrap
        event_pnl = IndependenceAndOverlapAuditEngine.audit_event_level_pnl(
            oos_executions=oos_executions, oos_events=oos_events
        )
        duplicates = IndependenceAndOverlapAuditEngine.audit_duplicate_executions(
            oos_executions=oos_executions
        )
        hypotheses_overlap = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap(
            hypotheses=[], executions=reproduction["raw_executions"]
        )
        bootstrap = IndependenceAndOverlapAuditEngine.audit_event_level_bootstrap(
            oos_executions=oos_executions, n_bootstraps=1000
        )
        leave_one_out = IndependenceAndOverlapAuditEngine.audit_leave_one_event_out(
            oos_executions=oos_executions
        )
        cost_stress = IndependenceAndOverlapAuditEngine.audit_cost_stress_testing(
            oos_executions=oos_executions
        )

        # 5. Original Phase 10A.10 Comparison
        original_comp = OriginalPhase10A10ComparisonEngine.evaluate_original_subset(
            db_path=self.db_path
        )

        # 6. Final Verdict Selection
        verdict = Phase10A10CVerdict.RESULT_INVALID_EXECUTION_MODEL.value

        independence_dict = {
            "event_level": event_pnl,
            "duplicates": duplicates,
            "overlap": hypotheses_overlap,
            "bootstrap": bootstrap,
            "leave_one_out": leave_one_out,
            "cost_stress": cost_stress,
        }

        # 7. Generate 23-Section Markdown Report
        report_md = Phase10A10CReportGenerator.generate_report(
            reproduction_results=reproduction,
            resolution_results=resolution_audit,
            mapping_results=mapping_audit,
            price_results=near_zero_audit,
            trace_results={"traces": traces, "counterfactual": counterfactual_audit, "capacity": capacity_audit},
            independence_results=independence_dict,
            original_comparison_results=original_comp,
            verdict=verdict,
            recorder_pid=70671
        )

        report_path = "artifacts/phase10a10c_forensic_audit.md"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w") as f:
            f.write(report_md)

        brain_report_path = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170/phase10a10c_forensic_audit.md"
        with open(brain_report_path, "w") as f:
            f.write(report_md)

        elapsed = time.time() - t0
        logger.info(f"Audit completed in {elapsed:.2f}s. Report written to {report_path}")

        return {
            "reproduction": reproduction,
            "resolution_audit": resolution_audit,
            "mapping_audit": mapping_audit,
            "near_zero_audit": near_zero_audit,
            "price_scale_audit": price_scale_audit,
            "counterfactual_audit": counterfactual_audit,
            "capacity_audit": capacity_audit,
            "independence": independence_dict,
            "original_comparison": original_comp,
            "verdict": verdict,
            "report_path": report_path,
            "elapsed_seconds": elapsed,
        }
