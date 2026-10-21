@echo off
chcp 65001 >nul
rem daily tietu: render the first post without a draft, then create the draft.
rem Posts that already have a draft are skipped, so re-running is safe. Never publishes.
cd /d "E:\Project\tietu-parenting"
if not exist "E:\Project\tietu-parenting\logs" mkdir "E:\Project\tietu-parenting\logs"
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
echo [%date% %time%] start >> "E:\Project\tietu-parenting\logs\daily-tietu.log"
"%PY%" "E:\Project\tietu-parenting\scripts\tietu_queue.py" --style comic --limit 1 --commit >> "E:\Project\tietu-parenting\logs\daily-tietu.log" 2>&1
echo [%date% %time%] end rc=%errorlevel% >> "E:\Project\tietu-parenting\logs\daily-tietu.log"
