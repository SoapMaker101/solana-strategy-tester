"""
Тест на потокобезопасность WarnDedup.

Проверяет, что warn_once корректно работает в многопоточной среде.
"""
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from backtester.utils.warn_dedup import WarnDedup


def test_warn_dedup_threadsafe():
    """
    Тест на потокобезопасность: 10 потоков, 1000 вызовов одного и того же key.
    
    Ожидание:
    - counts[key] == 1000
    - warn_once вернул True ровно 1 раз
    """
    dedup = WarnDedup()
    key = "test_key"
    
    # Счетчик для подсчета количества True (должен быть 1)
    true_count_lock = Lock()
    true_count = 0
    
    def worker(worker_id: int, calls_per_worker: int):
        """Рабочая функция для потока."""
        nonlocal true_count
        local_true_count = 0
        
        for i in range(calls_per_worker):
            result = dedup.warn_once(key, f"Test message from worker {worker_id}, call {i}", category="TEST")
            if result:
                local_true_count += 1
        
        # Атомарно увеличиваем счетчик
        with true_count_lock:
            nonlocal true_count
            true_count += local_true_count
    
    # Запускаем 10 потоков, каждый делает 100 вызовов (итого 1000)
    num_workers = 10
    calls_per_worker = 100
    total_calls = num_workers * calls_per_worker
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(worker, worker_id, calls_per_worker)
            for worker_id in range(num_workers)
        ]
        
        # Ждем завершения всех потоков
        for future in as_completed(futures):
            future.result()
    
    # Проверяем результаты
    summary = dedup.summary(top_n=10)
    
    # Проверяем, что counts[key] == 1000
    assert dedup._counts[key] == total_calls, f"Expected {total_calls} calls, got {dedup._counts[key]}"
    
    # Проверяем, что warn_once вернул True ровно 1 раз
    assert true_count == 1, f"Expected exactly 1 True return, got {true_count}"
    
    # Проверяем, что summary содержит правильную информацию
    assert f"unique=1" in summary
    assert f"total={total_calls}" in summary
    assert key in summary


def test_warn_dedup_multiple_keys():
    """
    Тест с несколькими разными ключами в параллельном режиме.
    """
    dedup = WarnDedup()
    keys = ["key1", "key2", "key3"]
    
    def worker(key: str, num_calls: int):
        """Рабочая функция для потока."""
        for i in range(num_calls):
            dedup.warn_once(key, f"Message for {key}, call {i}", category="TEST")
    
    # Запускаем по потоку на каждый ключ
    num_calls_per_key = 50
    
    with ThreadPoolExecutor(max_workers=len(keys)) as executor:
        futures = [
            executor.submit(worker, key, num_calls_per_key)
            for key in keys
        ]
        
        for future in as_completed(futures):
            future.result()
    
    # Проверяем результаты
    assert len(dedup._counts) == len(keys), f"Expected {len(keys)} unique keys, got {len(dedup._counts)}"
    
    for key in keys:
        assert dedup._counts[key] == num_calls_per_key, f"Expected {num_calls_per_key} calls for {key}, got {dedup._counts[key]}"
    
    summary = dedup.summary(top_n=10)
    assert f"unique={len(keys)}" in summary
    assert f"total={len(keys) * num_calls_per_key}" in summary


def test_warn_dedup_summary_empty():
    """
    Тест summary для пустого хранилища.
    """
    dedup = WarnDedup()
    summary = dedup.summary()
    assert "no warnings" in summary.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])






























