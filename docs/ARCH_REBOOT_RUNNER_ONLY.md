# Архитектурный reboot: Runner-only, TO-BE

**Версия:** 1.0  
**Дата:** 2025-01-XX  
**Статус:** Архитектурное видение (TO-BE), не требует реализации

---

## Содержание

1. [Почему нужен reboot](#1-почему-нужен-reboot)
2. [AS-IS архитектура (кратко)](#2-as-is-архитектура-кратко)
3. [TO-BE архитектурные принципы](#3-to-be-архитектурные-принципы)
4. [Blueprint → Replay → Ledger модель](#4-blueprint--replay--ledger-модель)
5. [Reset как first-class portfolio policy](#5-reset-как-first-class-portfolio-policy)
6. [Research & Decision separation](#6-research--decision-separation)
7. [Migration map (НЕ implementation plan)](#7-migration-map-не-implementation-plan)
8. [Non-goals](#8-non-goals)
9. [Связанные документы](#9-связанные-документы)

---

## 1. Почему нужен reboot

### Проблемы legacy RR/RRD (кратко)

**Legacy стратегии (RR/RRD) смешивали уровни:**
- Strategy-level PnL считался независимо от портфеля
- Portfolio-level reset влиял на strategy-level метрики
- Нет четкого разделения между strategy intent и portfolio execution

**Последствия:**
- Двусмысленность в метриках (strategy PnL vs portfolio PnL)
- Сложность интерпретации reset-закрытых позиций
- Невозможность replay симуляции из blueprints

### Почему Runner-only

**Runner-only упрощает архитектуру:**
- Один тип стратегии (Runner) с единым контрактом
- Единая модель ladder exits (partial_exits + final_exit)
- Четкое разделение blueprint → replay → ledger

**Преимущества:**
- Меньше edge cases, больше детерминированности
- Проще тестирование и валидация
- Возможность replay симуляции

### Почему portfolio-first, а не strategy-first

**Portfolio-first означает:**
- Portfolio-level метрики являются source of truth
- Strategy-level метрики являются derived (вычисляются из portfolio)
- Reset/prune — это portfolio policy, не strategy behavior

**Strategy-first (legacy) означал:**
- Strategy-level PnL считался независимо
- Portfolio-level агрегаты были производными
- Reset влиял на strategy метрики напрямую

**Преимущества portfolio-first:**
- Единый source of truth (portfolio_positions.csv)
- Reset/prune не влияет на strategy intent
- Четкое разделение ответственности

---

## 2. AS-IS архитектура (кратко)

### Как сейчас течёт пайплайн

**Текущий пайплайн (AS-IS):**
1. Signals → Strategies (Runner)
2. StrategyOutput → PortfolioEngine
3. PortfolioEngine → Positions + Events
4. Reporter → CSV (positions, events, executions)
5. Stage A → stability metrics (window-based)
6. Stage B → selection (criteria-based)

**Где смешаны уровни:**
- `PortfolioEngine` работает с `StrategyOutput` (strategy-level), но создает portfolio-level artifacts
- Reset логика живет в `PortfolioEngine`, но влияет на Stage A метрики
- Stage A читает `portfolio_positions.csv`, но не должна интерпретировать reset reasons

**Где reset влияет на всё:**
- Reset закрывает позиции → влияет на `portfolio_positions.csv`
- `portfolio_positions.csv` → влияет на Stage A метрики
- Stage A метрики → влияют на Stage B selection
- Косвенное влияние: reset изменяет распределение PnL по окнам

### Основные проблемы AS-IS

**Проблема 1: Strategy intent смешан с portfolio execution**
- `StrategyOutput` содержит portfolio-level PnL (`pnl_sol`)
- Нет четкого разделения между blueprint (intent) и execution (portfolio)

**Проблема 2: Reset как portfolio policy, но влияет на research**
- Reset — это portfolio policy (не стратегия)
- Stage A должна игнорировать reset reasons, но reset влияет на распределение PnL

**Проблема 3: Нет четкого контракта между уровнями**
- Stage A использует `portfolio_positions.csv`, но не ясно, что Stage A может/не может делать
- Stage B использует `strategy_stability.csv`, но не ясно, что Stage B может/не может делать

---

## 3. TO-BE архитектурные принципы

### Обязательные аксиомы

**Strategy = intent (Blueprint):**
- Strategy описывает "что хотела стратегия" (entry, partial exits, final exit)
- Strategy НЕ содержит portfolio-level метрик (size, fees, pnl_sol)
- Strategy intent независима от portfolio policy (reset/prune)

**Portfolio = деньги и риск:**
- Portfolio управляет балансом, capacity, exposure
- Portfolio применяет portfolio policy (reset/prune)
- Portfolio создает canonical ledger (positions, events, executions)

**Reset = portfolio policy, не стратегия:**
- Reset — это portfolio-level механизм управления рисками
- Reset НЕ является частью strategy intent
- Reset влияет на execution (закрывает позиции), но не влияет на blueprint

**Stage A = observation:**
- Stage A наблюдает за executed positions (читает `portfolio_positions.csv`)
- Stage A НЕ интерпретирует reset reasons (reset — это portfolio policy)
- Stage A вычисляет метрики устойчивости (window-based aggregation)

**Stage B = decision:**
- Stage B принимает решения на основе Stage A метрик
- Stage B НЕ должна "догадываться" о причинах плохих метрик (reset, bad strategy, etc.)
- Stage B использует четкие критерии (survival_rate, worst_window_pnl, variance)

**Audit = hard gate:**
- Audit проверяет инварианты (P0/P1/P2)
- P0 аномалии блокируют Stage A/B
- Audit не исправляет ошибки (только обнаруживает)

---

## 4. Blueprint → Replay → Ledger модель

### StrategyTradeBlueprint

**Blueprint описывает strategy intent без портфеля и денег:**

```
StrategyTradeBlueprint:
  - signal_id: str
  - strategy_id: str
  - contract_address: str
  - entry_time: datetime
  - entry_price_raw: float
  - partial_exits: list[PartialExitBlueprint]
  - final_exit: Optional[FinalExitBlueprint]
  - realized_multiple: float
  - max_xn_reached: float
  - reason: str
```

**Что blueprint НЕ содержит:**
- SOL size (это portfolio-level)
- Fees (это portfolio-level)
- pnl_sol (это portfolio-level)

**Смысл:** Blueprint описывает "что хотела стратегия", но не содержит portfolio-level исполнения.

### PortfolioReplay

**Replay строит portfolio ledger из blueprints:**

```
PortfolioReplay.replay(
  blueprints: List[StrategyTradeBlueprint],
  portfolio_config: PortfolioConfig,
  market_data: Optional[MarketData] = None,
) -> PortfolioResult
```

**Алгоритм:**
1. Сортировка blueprints по `entry_time`
2. Для каждого blueprint: проверка capacity/allocation
3. Если проходит: создание `POSITION_OPENED` + execution (entry)
4. Для каждого `partial_exit`: создание `POSITION_PARTIAL_EXIT` + execution
5. Если `final_exit` существует: создание `POSITION_CLOSED` + execution
6. Применение portfolio policy (reset/prune)

**Смысл:** Replay отделяет strategy intent (blueprint) от portfolio execution (ledger).

### Canonical Ledger

**Ledger — это source of truth для всех решений портфеля:**

- `portfolio_positions.csv` — positions-level агрегат (source of truth для Stage A)
- `portfolio_events.csv` — канонический event ledger (source of truth для audit)
- `portfolio_executions.csv` — execution-level дебаг (source of truth для prices/slippage)

**Связь:**
- Blueprint → Replay → Ledger (односторонняя)
- Ledger → Stage A/B (односторонняя, read-only)

### Determinism guarantees

**Гарантии детерминированности:**
- Одинаковые blueprints + portfolio_config → одинаковый ledger
- Одинаковый ledger → одинаковые Stage A/B метрики
- Reset/prune детерминированы (зависят только от состояния портфеля)

**Что НЕ гарантируется:**
- Детерминированность зависит от входных данных (signals, candles)
- Параллельная обработка может влиять на порядок (но результаты консистентны)

---

## 5. Reset как first-class portfolio policy

### Profit reset

**Profit reset — portfolio-level механизм фиксации прибыли:**

- Триггер: `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
- Действие: закрытие всех открытых позиций + сброс `cycle_start_equity`
- Результат: `PORTFOLIO_RESET_TRIGGERED` событие + `POSITION_CLOSED` события с `reason="profit_reset"`

**Почему reset не должен жить в Stage A/B:**
- Reset — это portfolio policy, не strategy behavior
- Stage A/B — это observation/decision, не portfolio management
- Reset влияет на execution (закрывает позиции), но не влияет на blueprint

### Capacity prune

**Capacity prune — portfolio-level механизм управления capacity:**

- Триггер: capacity pressure (open_ratio, blocked_ratio, avg_hold_days)
- Действие: закрытие ~50% "плохих" позиций (без сброса profit cycle)
- Результат: `POSITION_CLOSED` события с `reason="capacity_prune"`

**Почему prune не должен жить в Stage A/B:**
- Prune — это portfolio policy, не strategy behavior
- Stage A/B читает executed positions, но не управляет capacity

### Где reset должен быть виден, а где игнорирован

**Где reset должен быть виден:**
- `portfolio_positions.csv`: поля `closed_by_reset`, `reset_reason` (для observability)
- `portfolio_events.csv`: событие `PORTFOLIO_RESET_TRIGGERED`
- `portfolio_policy_summary.csv`: статистика reset/prune
- Audit: проверка консистентности reset событий

**Где reset должен быть игнорирован:**
- **Stage A:** Читает `closed_by_reset` / `reset_reason`, но НЕ фильтрует и НЕ корректирует метрики
- **Stage B:** Использует Stage A метрики как есть, НЕ интерпретирует reset reasons

**Почему:**
- Reset — это portfolio policy, не strategy quality
- Stage A/B должны оценивать стратегию по executed positions, независимо от portfolio policy

---

## 6. Research & Decision separation

### Почему Stage A нельзя "лечить"

**Stage A — это observation layer:**
- Stage A наблюдает за executed positions (читает `portfolio_positions.csv`)
- Stage A вычисляет метрики устойчивости (window-based aggregation)
- Stage A НЕ должна фильтровать или корректировать данные

**Что Stage A НЕ должна делать:**
- ❌ Фильтровать позиции по `closed_by_reset`
- ❌ Корректировать метрики на основе `reset_reason`
- ❌ Пересчитывать `pnl_sol` из execution prices
- ❌ "Лечить" данные (Stage A только читает и агрегирует)

**Почему:**
- Stage A должна быть честной observation
- Фильтрация/корректировка скрывает реальное поведение стратегии
- Reset — это portfolio policy, не strategy quality

### Почему Stage B нельзя "догадываться"

**Stage B — это decision layer:**
- Stage B принимает решения на основе Stage A метрик
- Stage B использует четкие критерии (survival_rate, worst_window_pnl, variance)
- Stage B НЕ должна "догадываться" о причинах плохих метрик

**Что Stage B НЕ должна делать:**
- ❌ Интерпретировать `failed_reasons` как "reset caused failure"
- ❌ Корректировать критерии на основе reset статистики
- ❌ "Догадываться" о причинах низкого `survival_rate`

**Почему:**
- Stage B должна принимать решения на основе метрик, а не причин
- "Догадки" увеличивают сложность и снижают прозрачность
- Reset — это portfolio policy, не strategy quality

### Где допустимы only diagnostics

**Diagnostics — для понимания, но не для решений:**

- `portfolio_policy_summary.csv` — диагностика reset/prune (не влияет на Stage A/B)
- `failed_reasons` в Stage B — объяснение, почему стратегия не прошла (diagnostic, не decision)
- `closed_by_reset` / `reset_reason` в positions — observability (не влияет на Stage A метрики)

**Правило:** Diagnostics существуют для observability и explainability, но не должны влиять на Stage A/B метрики и решения.

---

## 7. Migration map (НЕ implementation plan)

### Какие зоны стабильны

**Стабильные зоны (не требуют изменений):**
- **Canonical ledger:** `portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv` — source of truth, не меняются
- **Stage A/B контракты:** Метрики и критерии определены, обратная совместимость гарантирована
- **Reset логика:** Profit reset и capacity prune работают корректно, не требуют изменений

**Почему стабильны:**
- Эти зоны реализуют четкие контракты
- Изменения потребуют нового baseline
- Обратная совместимость важна

### Какие потенциально меняются в будущем

**Потенциально меняются (в будущих версиях):**
- **Blueprint → Replay модель:** Полная реализация PortfolioReplay (сейчас частично реализовано)
- **Strategy intent separation:** Полное разделение blueprint и execution (сейчас StrategyOutput содержит portfolio-level PnL)
- **Stage A/B интерфейсы:** Более четкие контракты (сейчас используются CSV файлы)

**Почему потенциально меняются:**
- Эти зоны не полностью реализуют TO-BE видение
- Изменения требуют нового baseline
- Нет срочной необходимости (AS-IS работает корректно)

### Что потребует нового baseline

**Изменения, требующие нового baseline:**
- Изменение структуры CSV файлов (добавление/удаление колонок)
- Изменение Stage A/B метрик (изменение формул)
- Изменение reset логики (изменение триггеров/действий)
- Изменение canonical event types (добавление/удаление типов)

**Почему:**
- Эти изменения ломают обратную совместимость
- Существующие тесты и baseline результаты становятся невалидными
- Требуется миграция существующих данных

---

## 8. Non-goals

### Чётко зафиксировать: Что документ НЕ предлагает делать сейчас

**Документ НЕ требует:**
- ❌ Немедленной реализации PortfolioReplay (сейчас работает PortfolioEngine)
- ❌ Изменения структуры CSV файлов (текущая структура работает)
- ❌ Изменения Stage A/B метрик (текущие метрики корректны)
- ❌ Изменения reset логики (текущая логика работает)

**Документ НЕ является:**
- ❌ Implementation plan (это архитектурное видение)
- ❌ Roadmap (нет временных рамок)
- ❌ Требованием к изменениям (AS-IS работает корректно)

**Документ ЯВЛЯЕТСЯ:**
- ✅ Архитектурным якорем (TO-BE видение)
- ✅ Руководством для будущих изменений
- ✅ Объяснением принципов (почему система так устроена)

### Какие изменения запрещены без новой версии

**Запрещено без новой версии:**
- Изменение структуры CSV файлов (ломает обратную совместимость)
- Изменение Stage A/B метрик (ломает baseline)
- Изменение reset логики (ломает существующие результаты)
- Изменение canonical event types (ломает audit)

**Почему:**
- Эти изменения требуют нового baseline
- Обратная совместимость важна для существующих пользователей
- Требуется миграция существующих данных

---

## 9. Связанные документы

- `docs/VARIABLES_REFERENCE.md` — канонический справочник всех переменных и метрик
- `docs/CANONICAL_LEDGER_CONTRACT.md` — структура событий и инварианты
- `docs/STAGE_A_B_PRINCIPLES_v2.2.md` — контракты Stage A/B и метрики
- `docs/PRUNE_AND_PROFIT_RESET_RULES.md` — reset mechanics и правила
- `docs/RESET_IMPACT_ON_STAGE_A_B_v2.2.md` — влияние reset на Stage A/B
- `docs/PIPELINE_GUIDE.md` — общий пайплайн и source of truth
- `docs/ARCHITECTURE.md` — AS-IS архитектура (текущее состояние)

---

*Документ создан: 2025-01-XX*  
*Версия архитектурного видения: 1.0*  
*Статус: TO-BE видение, не требует реализации*
