@echo off
cd /d "C:\BudgetTracker\ua-budget-tracker-python"
waitress-serve --listen=0.0.0.0:8000 wsgi:app
pause
