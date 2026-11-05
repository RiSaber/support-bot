@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
	echo Создаю окружение...
	python -m venv .venv
)
.venv\Scripts\python -m pip install -q -r requirements.txt
if not exist .env (
	echo Нет файла .env. Скопируйте .env.example в .env и заполните ключи.
	pause
	exit /b 1
)
echo Бот запускается. Чтобы остановить, закройте это окно.
.venv\Scripts\python bot.py
pause
