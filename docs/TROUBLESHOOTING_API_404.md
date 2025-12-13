# Устранение ошибки 404 от GeckoTerminal API

## Проблема

При запросе OHLCV данных от GeckoTerminal API возвращается ошибка 404:

```json
{
  "errors": [{"status": "404", "title": "Not Found"}],
  "meta": {"ref_id": "..."}
}
```

## Возможные причины

### 1. Пул не найден или деактивирован

**Симптомы:**
- Ошибка 404 при запросе `/pools/{pool_id}/ohlcv/...`
- Pool_id был получен ранее, но теперь пул удален или неактивен

**Решение:**
- ✅ Улучшена логика выбора пула - теперь выбирается пул с наибольшей ликвидностью
- ✅ Добавлена проверка наличия пулов перед выбором
- ✅ При ошибке 404 система пытается использовать кеш, если он доступен

### 2. Пул не имеет данных для запрашиваемого таймфрейма

**Симптомы:**
- Ошибка 404 для конкретного таймфрейма (например, `15m`)
- Другие таймфреймы могут работать

**Решение:**
- Проверьте, поддерживает ли пул запрашиваемый таймфрейм
- Попробуйте использовать другой таймфрейм (например, `1m` вместо `15m`)
- Используйте кешированные данные, если они доступны

### 3. Timestamp вне допустимого диапазона

**Симптомы:**
- Timestamp в будущем (больше текущего времени)
- Timestamp слишком старый (больше 6 месяцев назад)

**Решение:**
- ✅ Добавлена проверка timestamp - система предупреждает, если timestamp в будущем
- ✅ Добавлено предупреждение, если timestamp старше 6 месяцев (лимит GeckoTerminal API)
- Система автоматически использует текущее время, если end_time в будущем

### 4. Неправильный формат запроса

**Симптомы:**
- Ошибка 404 при использовании aggregate параметра
- Неправильный endpoint

**Проверка:**
- Для `15m` используется: `/ohlcv/minute?aggregate=15`
- Для `1m` используется: `/ohlcv/minute` (без aggregate)
- Формат корректный согласно документации GeckoTerminal API

## Улучшения в коде

### 1. Улучшенный выбор пула

**Было:**
```python
return r.json()["data"][0]["attributes"]["address"]  # Первый пул
```

**Стало:**
```python
# Выбираем пул с наибольшей ликвидностью (reserve_in_usd)
best_pool = None
max_reserve = 0.0
for pool in pools:
    reserve = float(pool["attributes"].get("reserve_in_usd", 0))
    if reserve > max_reserve:
        max_reserve = reserve
        best_pool = pool
```

**Преимущества:**
- Выбирается наиболее ликвидный пул
- Меньше вероятность, что пул будет удален или неактивен
- Более стабильные данные

### 2. Улучшенная обработка ошибок 404

**Добавлено:**
- Детальное логирование причин ошибки 404
- Автоматический fallback на кеш при ошибке
- Проверка структуры ответа API

**Пример вывода:**
```
❌ Pool 43dizkRrrh4CYCN74yBijhr9BwtVTByHfG3RpdpCMh7kY returned 404. Possible reasons:
   1. Pool was removed or deactivated
   2. Pool has no trading history
   3. Requested timeframe (15m) is not available
   4. Timestamp 1765367100 is too far in the past/future
⚠️ Falling back to cached candles due to 404 error
```

### 3. Проверка timestamp

**Добавлено:**
- Проверка, что timestamp не в будущем
- Предупреждение, если timestamp старше 6 месяцев
- Автоматическая коррекция end_time, если он в будущем

## Рекомендации

### Для разработчиков

1. **Используйте кеширование:**
   - Система автоматически использует кеш при ошибках API
   - Кеш помогает избежать повторных запросов к неработающим пулам

2. **Проверяйте пулы перед использованием:**
   - Используйте пулы с наибольшей ликвидностью
   - Проверяйте, что пул активен и имеет торговую историю

3. **Обрабатывайте ошибки:**
   - Всегда проверяйте наличие кеша при ошибках API
   - Логируйте детальную информацию об ошибках

### Для пользователей

1. **Если получаете 404:**
   - Проверьте, что токен существует и имеет активные пулы
   - Попробуйте использовать другой таймфрейм
   - Используйте кешированные данные, если они доступны

2. **Если пул не найден:**
   - Токен может быть удален или неактивен
   - Пул может не иметь данных для запрашиваемого периода
   - Попробуйте другой токен или временной диапазон

## Примеры

### Пример 1: Пул не найден

```python
from backtester.infrastructure.price_loader import GeckoTerminalPriceLoader

loader = GeckoTerminalPriceLoader(timeframe="15m")

# Если пул не найден, система попытается использовать кеш
candles = loader.load_prices("INVALID_TOKEN_ADDRESS", start, end)
# ❌ Pool ... returned 404
# ⚠️ Falling back to cached candles due to 404 error
```

### Пример 2: Timestamp в будущем

```python
from datetime import datetime, timezone, timedelta

# Timestamp в будущем - система автоматически использует текущее время
future_time = datetime.now(timezone.utc) + timedelta(days=1)
candles = loader.load_prices("TOKEN", start, future_time)
# ⚠️ Warning: end_time is in the future, using current time instead
```

### Пример 3: Timestamp слишком старый

```python
# Timestamp старше 6 месяцев - система предупредит
old_time = datetime.now(timezone.utc) - timedelta(days=200)
candles = loader.load_prices("TOKEN", old_time, end)
# ⚠️ Warning: Requested timestamp is more than 6 months ago
```

## Дополнительная информация

- **GeckoTerminal API Docs:** https://apiguide.geckoterminal.com/
- **Rate Limit:** 30 запросов в минуту
- **Исторические данные:** До 6 месяцев назад
- **Поддерживаемые таймфреймы:** `1m`, `5m`, `15m`, `1h`, `4h`, `12h`, `1d`

---

*Документация обновлена: 2025-01-XX*



