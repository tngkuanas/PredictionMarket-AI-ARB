"""Runner script for Phase 10A.9-A Forensic Audit."""

import logging
from src.phase10a9_audit.pipeline import Phase10A9AuditPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Phase10A9AuditRunner")


def main():
    logger.info("Initializing Phase 10A.9-A Forensic Audit...")
    pipeline = Phase10A9AuditPipeline()
    results = pipeline.run_audit()
    logger.info(f"Audit Complete! Verdict: {results['verdict']}")
    logger.info(f"Reason: {results['verdict_reason']}")


if __name__ == "__main__":
    main()
