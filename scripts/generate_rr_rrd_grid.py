#!/usr/bin/env python3
"""
Генератор стратегий RR + RRD для исследовательского прогона.

Генерирует config/strategies_rr_rrd_grid.yaml со всеми комбинациями параметров.
"""

from pathlib import Path
import os


def generate_rr_strategies():
    """Генерирует список RR стратегий."""
    strategies = []
    
    # tp_pct: от 50 до 400, шаг 10
    # sl_pct: от 20 до 75, шаг 5
    # Ограничение: sl_pct <= tp_pct / 2
    
    for tp in range(50, 401, 10):  # 50, 60, 70, ..., 400
        for sl in range(20, 76, 5):  # 20, 25, 30, ..., 75
            if sl <= tp / 2:
                strategy = {
                    'name': f'RR_TP{tp}_SL{sl}',
                    'type': 'RR',
                    'params': {
                        'tp_pct': tp,
                        'sl_pct': sl,
                        'max_minutes': 42000,
                        'max_price_jump_pct': 30.0
                    }
                }
                strategies.append(strategy)
    
    return strategies


def generate_rrd_strategies(rr_strategies):
    """Генерирует список RRD стратегий для каждой RR стратегии."""
    strategies = []
    
    # drawdown_entry_pct: от 10 до 30, шаг 5
    drawdown_values = list(range(10, 31, 5))  # 10, 15, 20, 25, 30
    
    for rr_strategy in rr_strategies:
        tp = rr_strategy['params']['tp_pct']
        sl = rr_strategy['params']['sl_pct']
        
        for dd in drawdown_values:
            strategy = {
                'name': f'RRD_DD{dd}_TP{tp}_SL{sl}_W180',
                'type': 'RRD',
                'params': {
                    'drawdown_entry_pct': dd,
                    'tp_pct': tp,
                    'sl_pct': sl,
                    'max_minutes': 42000,
                    'entry_wait_minutes': 180,
                    'max_price_jump_pct': 30.0
                }
            }
            strategies.append(strategy)
    
    return strategies


def main():
    """Генерирует файл конфигурации стратегий."""
    # Генерируем стратегии
    rr_strategies = generate_rr_strategies()
    rrd_strategies = generate_rrd_strategies(rr_strategies)
    
    # Объединяем все стратегии
    all_strategies = rr_strategies + rrd_strategies
    
    # Подготавливаем содержимое файла
    header_comment = f"""# config/strategies_rr_rrd_grid.yaml
# Автоматически сгенерированный файл с параметрической сеткой стратегий RR и RRD
# 
# Количество стратегий:
#   RR: {len(rr_strategies)}
#   RRD: {len(rrd_strategies)}
#   Всего: {len(all_strategies)}
#
# Параметры генерации:
#   RR: tp_pct от 50 до 400 (шаг 10), sl_pct от 20 до 75 (шаг 5), ограничение sl_pct <= tp_pct / 2
#   RRD: для каждой RR комбинации, drawdown_entry_pct от 10 до 30 (шаг 5), entry_wait_minutes = 180

"""
    
    # Формируем YAML содержимое
    yaml_content = header_comment
    
    # Добавляем RR стратегии
    yaml_content += "# -----------------------------\n"
    yaml_content += "# RR стратегии\n"
    yaml_content += "# -----------------------------\n"
    for strategy in rr_strategies:
        yaml_content += f"- name: {strategy['name']}\n"
        yaml_content += f"  type: {strategy['type']}\n"
        yaml_content += "  params:\n"
        for key, value in strategy['params'].items():
            yaml_content += f"    {key}: {value}\n"
        yaml_content += "\n"
    
    # Добавляем RRD стратегии
    yaml_content += "# -----------------------------\n"
    yaml_content += "# RRD стратегии\n"
    yaml_content += "# -----------------------------\n"
    for strategy in rrd_strategies:
        yaml_content += f"- name: {strategy['name']}\n"
        yaml_content += f"  type: {strategy['type']}\n"
        yaml_content += "  params:\n"
        for key, value in strategy['params'].items():
            yaml_content += f"    {key}: {value}\n"
        yaml_content += "\n"
    
    # Определяем путь к выходному файлу
    # Используем текущую рабочую директорию как базовую
    try:
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
    except NameError:
        # Если __file__ не определен (например, при exec), используем текущую директорию
        project_root = Path(os.getcwd())
    
    output_file = project_root / 'config' / 'strategies_rr_rrd_grid.yaml'
    
    # Создаем директорию если её нет
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Записываем файл
    output_file.write_text(yaml_content, encoding='utf-8')
    
    # Выводим summary
    print("=" * 60)
    print("Генерация стратегий завершена")
    print("=" * 60)
    print(f"RR стратегий:     {len(rr_strategies)}")
    print(f"RRD стратегий:    {len(rrd_strategies)}")
    print(f"Всего стратегий:  {len(all_strategies)}")
    print("=" * 60)
    print(f"Файл сохранен: {output_file}")
    print("=" * 60)


if __name__ == '__main__':
    main()













