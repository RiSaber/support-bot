"""Ядро ассистента: регламент + системный промпт + Gemini + проверка ответа кодом.

Защита от галлюцинаций в три слоя:
1. Системный промпт: отвечать только по базе, всё остальное — оператору.
2. temperature=0: модель не «фантазирует».
3. validate(): если в ответе есть цифры, которых нет ни в базе, ни в вопросе,
   или обещание скидки — ответ не уходит клиенту, вместо него безопасный шаблон.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_PATH = BASE_DIR / "knowledge.md"
PROMPT_PATH = BASE_DIR / "prompt.md"

ESCALATE_TAG = "[ОПЕРАТОР]"
OPERATOR_TEXT = "Передаю ваш вопрос оператору — он ответит вам в этом чате."
# Безопасный ответ, если модель недоступна или ответ не прошёл проверку
FALLBACK_TEXT = "Не могу точно ответить на этот вопрос. " + OPERATOR_TEXT
MAX_QUESTION_LEN = 1000

# Обещания, которые противоречат регламенту, даже если цифр нет
FORBIDDEN_PATTERNS = [
    # «дадим скидку», «могу предложить скидку», «сделаем скидку»
    re.compile(r"(дади[мт]|дам|предостав\w*|оформ\w*|сдела\w*|предлож\w*|дарим)\s+(вам\s+)?(персональн\w+\s+)?скидк", re.I),
    re.compile(r"промокод", re.I),
    # «вернём деньги сразу» — при браке так обещать нельзя
    re.compile(r"(сразу|немедленно|сегодня же)\s+верн", re.I),
    re.compile(r"верн\w*\s+(вам\s+)?деньги\s+(сразу|немедленно)", re.I),
]

NEGATION_BEFORE = re.compile(r"\b(не|нельзя|никак)\s+(\w+\s+)?$", re.I)
NEGATION_AFTER = re.compile(r"\bне\s+(можем|могу|получится|обещаем|предусмотрен\w*|положен\w*)", re.I)

log = logging.getLogger("assistant")


@dataclass
class Reply:
    text: str          # что увидит клиент
    escalate: bool     # нужно ли звать оператора
    source: str        # "llm" | "fallback"
    reason: str = ""   # почему сработал fallback (для логов и краш-теста)


def load_knowledge() -> str:
    return KNOWLEDGE_PATH.read_text(encoding="utf-8")


def build_system_prompt(knowledge: str | None = None) -> str:
    knowledge = knowledge if knowledge is not None else load_knowledge()
    return PROMPT_PATH.read_text(encoding="utf-8").replace("{knowledge}", knowledge.strip())


def _numbers(text: str) -> set[str]:
    """Все числа из текста; «2 490», «2,490» и «2490» считаются одним числом."""
    joined = re.sub(r"(?<=\d)[\s  ,.](?=\d{3}\b)", "", text)
    return set(re.findall(r"\d+", joined))


def validate(answer: str, question: str, knowledge: str) -> list[str]:
    """Возвращает список нарушений. Пустой список — ответ можно отправлять."""
    problems = []
    # Номера пунктов регламента («1.», «2.») — не факты, их не разрешаем
    facts = re.sub(r"(?m)^\s*\d+\.\s", "", knowledge)
    allowed = _numbers(facts) | _numbers(question)
    extra = _numbers(answer) - allowed
    if extra:
        problems.append("цифры не из базы: " + ", ".join(sorted(extra)))
    for pattern in FORBIDDEN_PATTERNS:
        for m in pattern.finditer(answer):
            # «не дадим скидку», «сразу вернуть мы не можем» — это отказ, а не обещание
            before = answer[max(0, m.start() - 25):m.start()]
            after = answer[m.end():m.end() + 30]
            if NEGATION_BEFORE.search(before) or NEGATION_AFTER.search(after):
                continue
            problems.append("запрещённое обещание: " + m.group(0))
            break
    if not answer.strip():
        problems.append("пустой ответ")
    return problems


DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-flash-lite-latest"
ATTEMPTS_PER_MODEL = 2
RETRY_DELAY_SEC = 2
REQUEST_TIMEOUT_MS = 30_000


class Assistant:
    def __init__(self, api_key: str | None = None, models: str | None = None):
        self.client = genai.Client(
            api_key=api_key or os.environ["GEMINI_API_KEY"],
            # Тайм-аут запроса в мс: зависший запрос не должен блокировать ответ клиенту
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
        # Основная модель и запасные: бесплатный уровень иногда отвечает 503/429
        names = models or os.environ.get("GEMINI_MODELS") or DEFAULT_MODELS
        self.models = [m.strip() for m in names.split(",") if m.strip()]
        self.model = self.models[0]
        self.knowledge = load_knowledge()
        self.config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(self.knowledge),
            temperature=0,
        )

    async def _generate(self, question: str) -> tuple[str, str]:
        """Пробует модели по очереди с повтором. Возвращает (текст, модель)."""
        last_error: Exception | None = None
        for model in self.models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    response = await self.client.aio.models.generate_content(
                        model=model, contents=question, config=self.config
                    )
                    return (response.text or "").strip(), model
                except Exception as e:  # перегрузка, лимиты, сеть
                    last_error = e
                    log.warning("%s, попытка %d: %s", model, attempt + 1, str(e)[:120])
                    if "NOT_FOUND" in str(e):  # модель недоступна — сразу к следующей
                        break
                    await asyncio.sleep(RETRY_DELAY_SEC)
        raise last_error or RuntimeError("нет моделей")

    async def answer(self, question: str) -> Reply:
        question = question.strip()[:MAX_QUESTION_LEN]
        if not question:
            return Reply("Напишите, пожалуйста, ваш вопрос.", False, "fallback", "пустой вопрос")

        try:
            raw, used_model = await self._generate(question)
        except Exception as e:
            log.warning("Gemini недоступен: %s", e)
            return Reply(FALLBACK_TEXT, True, "fallback", f"ошибка API: {type(e).__name__}")

        escalate = ESCALATE_TAG in raw
        text = raw.replace(ESCALATE_TAG, "").strip()

        problems = validate(text, question, self.knowledge)
        if problems:
            log.warning("Ответ отклонён (%s): %r", "; ".join(problems), text)
            return Reply(FALLBACK_TEXT, True, "fallback", "; ".join(problems))

        if escalate:
            text = f"{text}\n\n{OPERATOR_TEXT}" if text else OPERATOR_TEXT
        return Reply(text, escalate, "llm", "" if used_model == self.model else f"запасная модель {used_model}")
