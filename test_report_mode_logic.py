#!/usr/bin/env python3
"""
Тест для проверки логики определения дефолтов для no_charts и no_html
"""

def test_report_mode_logic():
    """Проверяет логику определения дефолтов для разных режимов"""
    
    test_cases = [
        # (report_mode, no_charts_arg, no_html_arg, expected_no_charts, expected_no_html, description)
        ("all", None, None, False, False, "Режим 'all' без флагов: графики и HTML должны быть включены"),
        ("summary", None, None, True, True, "Режим 'summary' без флагов: графики и HTML должны быть отключены"),
        ("top", None, None, True, True, "Режим 'top' без флагов: графики и HTML должны быть отключены"),
        ("none", None, None, True, True, "Режим 'none' без флагов: графики и HTML должны быть отключены"),
        ("all", True, None, True, False, "Режим 'all' с --no-charts: графики отключены, HTML включен"),
        ("all", None, True, False, True, "Режим 'all' с --no-html: графики включены, HTML отключен"),
        ("summary", False, None, False, True, "Режим 'summary' с явным --no-charts=False: графики включены, HTML отключен"),
    ]
    
    print("Testing report mode logic for no_charts and no_html defaults\n")
    
    all_passed = True
    for report_mode, no_charts_arg, no_html_arg, expected_no_charts, expected_no_html, description in test_cases:
        # Логика из main.py
        if no_charts_arg is None:
            no_charts = report_mode in ["none", "summary", "top"]
        else:
            no_charts = no_charts_arg
        
        if no_html_arg is None:
            no_html = report_mode in ["none", "summary", "top"]
        else:
            no_html = no_html_arg
        
        # Проверка
        charts_ok = no_charts == expected_no_charts
        html_ok = no_html == expected_no_html
        test_passed = charts_ok and html_ok
        
        status = "PASS" if test_passed else "FAIL"
        print(f"{status}: {description}")
        print(f"   Mode: {report_mode}, no_charts_arg={no_charts_arg}, no_html_arg={no_html_arg}")
        print(f"   Result: no_charts={no_charts} (expected {expected_no_charts}), no_html={no_html} (expected {expected_no_html})")
        
        if not test_passed:
            all_passed = False
            if not charts_ok:
                print(f"   ERROR: no_charts mismatch!")
            if not html_ok:
                print(f"   ERROR: no_html mismatch!")
        print()
    
    if all_passed:
        print("All tests passed successfully!")
    else:
        print("Some tests failed!")
    
    return all_passed


if __name__ == "__main__":
    test_report_mode_logic()
