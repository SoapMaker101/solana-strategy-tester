# backtester/domain/execution_model.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .portfolio import FeeModel, PortfolioConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionProfileConfig:
    """
    Конфигурация профиля исполнения с reason-based slippage multipliers.
    """
    base_slippage_pct: float
    slippage_multipliers: Dict[str, float]  # entry, exit_tp, exit_sl, exit_timeout, exit_manual
    
    def slippage_for(self, event: str) -> float:
        """
        Возвращает slippage для конкретного события.
        
        :param event: Тип события: "entry", "exit_tp", "exit_sl", "exit_timeout", "exit_manual"
        :return: Slippage в долях (0.03 = 3%)
        """
        multiplier = self.slippage_multipliers.get(event, 1.0)
        return self.base_slippage_pct * multiplier


class ExecutionModel:
    """
    Центральная модель расчета цен с учетом slippage и комиссий.
    """
    
    def __init__(self, fee_model: "FeeModel", profile: ExecutionProfileConfig):
        self.fee_model = fee_model
        self.profile = profile
    
    @classmethod
    def from_config(cls, config: "PortfolioConfig") -> ExecutionModel:
        """
        Создает ExecutionModel из PortfolioConfig.
        """
        profile = get_profile(config)
        return cls(config.fee_model, profile)
    
    def apply_entry(self, price: float, event: str = "entry") -> float:
        """
        Применяет slippage к цене входа.
        
        Для покупки: effective_price = price * (1 + slippage)
        (платим больше при покупке)
        
        :param price: Исходная цена входа
        :param event: Тип события (по умолчанию "entry")
        :return: Эффективная цена входа с учетом slippage
        """
        slippage = self.profile.slippage_for(event)
        return price * (1.0 + slippage)
    
    def apply_exit(self, price: float, reason: str) -> float:
        """
        Применяет slippage к цене выхода на основе причины выхода.
        
        Для продажи: effective_price = price * (1 - slippage)
        (получаем меньше при продаже)
        
        :param price: Исходная цена выхода
        :param reason: Причина выхода: "tp", "sl", "timeout", "manual" или другие
        :return: Эффективная цена выхода с учетом slippage
        """
        # Маппинг reason на event
        event_map = {
            "tp": "exit_tp",
            "sl": "exit_sl",
            "timeout": "exit_timeout",
            "manual": "exit_manual",
        }
        event = event_map.get(reason, "exit_timeout")  # По умолчанию timeout
        
        slippage = self.profile.slippage_for(event)
        return price * (1.0 - slippage)
    
    def apply_fees(self, notional_sol: float) -> float:
        """
        Применяет комиссии к нотионалу (swap + LP fees).
        Network fee вычитается отдельно из баланса.
        
        :param notional_sol: Нотионал в SOL
        :return: Нотионал после вычета комиссий (swap + LP)
        """
        total_fee_pct = self.fee_model.swap_fee_pct + self.fee_model.lp_fee_pct
        return notional_sol * (1.0 - total_fee_pct)
    
    def network_fee(self) -> float:
        """
        Возвращает фиксированную комиссию сети в SOL.
        """
        return self.fee_model.network_fee_sol


def get_profile(config: "PortfolioConfig") -> ExecutionProfileConfig:
    """
    Получает профиль исполнения из конфигурации портфеля.
    
    Если указан execution_profile и есть profiles в fee_model, использует его.
    Если нет profiles, но есть legacy slippage_pct - создает дефолтный профиль с предупреждением.
    По умолчанию использует "realistic" профиль.
    """
    profile_name = getattr(config, 'execution_profile', 'realistic')
    
    # Проверяем наличие profiles в fee_model
    if hasattr(config.fee_model, 'profiles') and config.fee_model.profiles:
        if profile_name not in config.fee_model.profiles:
            raise ValueError(
                f"Execution profile '{profile_name}' not found in fee.profiles. "
                f"Available profiles: {list(config.fee_model.profiles.keys())}"
            )
        return config.fee_model.profiles[profile_name]
    
    # Legacy режим: используем slippage_pct без multipliers
    if hasattr(config.fee_model, 'slippage_pct') and config.fee_model.slippage_pct is not None:
        logger.warning(
            "Using legacy slippage_pct without profiles. "
            "Consider migrating to execution profiles for better control."
        )
        return ExecutionProfileConfig(
            base_slippage_pct=config.fee_model.slippage_pct,
            slippage_multipliers={
                "entry": 1.0,
                "exit_tp": 1.0,
                "exit_sl": 1.0,
                "exit_timeout": 1.0,
                "exit_manual": 1.0,
            }
        )
    
    # Дефолтный realistic профиль (если нет ни profiles, ни legacy slippage_pct)
    return ExecutionProfileConfig(
        base_slippage_pct=0.03,  # 3%
        slippage_multipliers={
            "entry": 1.0,
            "exit_tp": 0.7,
            "exit_sl": 1.2,
            "exit_timeout": 0.3,
            "exit_manual": 0.5,
        }
    )
