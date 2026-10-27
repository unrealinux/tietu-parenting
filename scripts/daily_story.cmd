@echo off
chcp 65001 >nul
rem daily story: pick the first story without a draft, render if images missing, create draft.
rem drafted slugs are recorded in output/story/_state.json; same online title is skipped. never publishes.
cd /d "E:\Project\tietu-parenting"
if not exist "E:\Project\tietu-parenting\logs" mkdir "E:\Project\tietu-parenting\logs"
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
echo [%date% %time%] start >> "E:\Project\tietu-parenting\logs\daily-story.log"
"%PY%" "E:\Project\tietu-parenting\scripts\publish_story.py" --next --commit >> "E:\Project\tietu-parenting\logs\daily-story.log" 2>&1
echo [%date% %time%] end rc=%errorlevel% >> "E:\Project\tietu-parenting\logs\daily-story.log"
