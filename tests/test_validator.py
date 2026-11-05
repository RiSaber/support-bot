"""Тесты проверки ответов (без обращения к Gemini)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import build_system_prompt, load_knowledge, validate  # noqa: E402

KB = load_knowledge()


def test_correct_answer_passes():
    assert validate("Наушники X1 стоят 2 490 ₽ и есть в наличии.", "сколько стоят?", KB) == []


def test_price_formats_are_same_number():
    assert validate("Цена 2490 ₽", "цена?", KB) == []
    assert validate("Цена 2,490 ₽", "цена?", KB) == []


def test_invented_price_rejected():
    assert validate("Сейчас наушники стоят 1 990 ₽.", "цена?", KB)


def test_invented_delivery_time_rejected():
    assert validate("Заказ 1842 приедет через 2 дня.", "доставка заказа 1842", KB)


def test_numbers_from_question_allowed():
    # Бот может повторить номер заказа и срок из вопроса
    answer = "Статус заказа 1842 я не вижу. Возврат возможен в течение 14 дней, 16-й день уже вне срока."
    assert validate(answer, "доставка заказа 1842, вернуть на 16-й день", KB) == []


def test_discount_promise_rejected():
    assert validate("Хорошо, дадим вам скидку.", "дай скидку", KB)
    assert validate("Могу предложить скидку 20%.", "дай скидку 20%", KB)
    assert validate("Держите промокод.", "скидку", KB)


def test_discount_refusal_passes():
    assert validate("Скидок у нас нет ни при каких условиях. Наушники X1 стоят 2 490 ₽.", "дай скидку 20%", KB) == []


def test_instant_refund_on_defect_rejected():
    assert validate("Вернём деньги сразу.", "брак", KB)


def test_refusals_with_negation_pass():
    assert validate("Решение после экспертизы, поэтому сразу вернуть средства мы не можем.", "брак", KB) == []
    assert validate("Мы не дадим скидку: скидок нет ни при каких условиях.", "скидку", KB) == []
    assert validate("Деньги сразу не обещаем.", "брак", KB) == []


def test_promise_with_unrelated_negation_rejected():
    assert validate("Сразу вернём деньги, не переживайте.", "брак", KB)


def test_empty_answer_rejected():
    assert validate("   ", "привет", KB)


def test_prompt_contains_knowledge():
    prompt = build_system_prompt()
    assert "2 490 ₽" in prompt and "{knowledge}" not in prompt
