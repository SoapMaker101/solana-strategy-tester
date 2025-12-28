"""
Потокобезопасный класс для дедупликации предупреждений.

Используется для предотвращения дублирования warning-сообщений в параллельном режиме.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional


class WarnDedup:
    """
    Потокобезопасный класс для дедупликации предупреждений.
    
    Гарантирует, что каждое уникальное предупреждение будет выведено только один раз,
    даже при параллельном выполнении из нескольких потоков.
    """
    
    def __init__(self):
        """Инициализирует хранилище для дедупликации."""
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}
        self._first_seen: Dict[str, tuple] = {}  # Хранит информацию о первом событии (опционально)
    
    def warn_once(self, key: str, msg: str, *, category: str = "WARN") -> bool:
        """
        Выводит предупреждение только один раз для каждого уникального ключа.
        
        :param key: Уникальный ключ для дедупликации (например, "{strategy}|first_candle_after_signal|{signal_id}|{contract}")
        :param msg: Сообщение для вывода
        :param category: Категория предупреждения (по умолчанию "WARN")
        :return: True если сообщение было выведено впервые, False если уже было выведено ранее
        """
        with self._lock:
            # Увеличиваем счетчик для этого ключа
            self._counts[key] = self._counts.get(key, 0) + 1
            
            # Если это первое появление - выводим сообщение
            if self._counts[key] == 1:
                # Сохраняем информацию о первом событии (опционально, для отладки)
                self._first_seen[key] = (msg, category)
                # Выводим сообщение под lock, чтобы избежать гонок при print()
                print(f"[{category}] {msg}")
                return True
            else:
                # Уже было выведено ранее
                return False
    
    def summary(self, top_n: int = 10) -> str:
        """
        Возвращает сводку по всем предупреждениям.
        
        :param top_n: Количество топ-ключей для вывода
        :return: Строка с сводкой
        """
        with self._lock:
            unique_count = len(self._counts)
            total_count = sum(self._counts.values())
            
            if unique_count == 0:
                return "[WARNING] Dedup warnings summary: no warnings"
            
            # Топ ключей по количеству
            top_items = sorted(self._counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
            top_str = ", ".join([f"{k}:{v}" for k, v in top_items])
            
            return f"[WARNING] Dedup warnings summary: unique={unique_count}, total={total_count}. Top: {top_str}"
























