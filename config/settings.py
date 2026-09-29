"""Application and quantitative engine configuration."""
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class APISettings(BaseModel):
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    # Fallback IP resolvers to protect against DNS poisoning/filtering
    polymarket_fallback_ips: List[str] = ["104.18.34.205", "172.64.153.51"]
    request_timeout_seconds: float = 15.0
    rate_limit_per_second: float = 5.0

class DatabaseSettings(BaseModel):
    db_path: Path = PROJECT_ROOT / "data" / "prediction_market.duckdb"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    features_dir: Path = PROJECT_ROOT / "data" / "features"

class LLMSettings(BaseModel):
    provider: str = Field(default="gemini", description="gemini, openai, anthropic, or mock")
    model_name: str = Field(default="gemini-2.5-flash", description="LLM model identifier")
    api_key: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4096

class ExecutionSettings(BaseModel):
    initial_cash: float = 100_000.0
    polymarket_maker_fee: float = 0.0
    polymarket_taker_fee: float = 0.001 # 0.1% or 0 on main books
    kalshi_contract_fee: float = 0.01  # Kalshi cents per contract formula approx
    slippage_bps: float = 10.0 # 10 basis points base slippage
    min_liquidity_usd: float = 500.0

class RiskSettings(BaseModel):
    max_position_per_market_usd: float = 5_000.0
    max_event_exposure_usd: float = 15_000.0
    max_correlated_exposure_usd: float = 25_000.0
    max_platform_exposure_usd: float = 60_000.0
    max_daily_loss_usd: float = 5_000.0
    max_strategy_drawdown_pct: float = 0.10 # 10%
    min_required_net_edge: float = 0.03 # 3% Net edge after costs
    max_holding_period_hours: float = 168.0 # 7 days
    relationship_break_zscore_stop: float = 3.5

class Settings(BaseModel):
    api: APISettings = Field(default_factory=APISettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

_settings_instance: Optional[Settings] = None

def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        # Ensure directories exist
        _settings_instance.db.raw_dir.mkdir(parents=True, exist_ok=True)
        _settings_instance.db.processed_dir.mkdir(parents=True, exist_ok=True)
        _settings_instance.db.features_dir.mkdir(parents=True, exist_ok=True)
    return _settings_instance
