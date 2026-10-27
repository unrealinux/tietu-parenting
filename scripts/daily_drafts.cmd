@echo off
chcp 65001 >nul
rem daily drafts: newest story + tietu into the WeChat draft box. never publishes.
rem story: pick first story without a draft (output/story/_state.json, plus online title check).
rem tietu: pick first N tietu posts without a draft, comic style.
cd /d "E:\Project\tietu-parenting"
if not exist "E:\Project\tietu-parenting\logs" mkdir "E:\Project\tietu-parenting\logs"
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
set TIETU_COUNT=3
set LOG=E:\Project\tietu-parenting\logs\daily-drafts.log
echo [%date% %time%] start >> "%LOG%"
"%PY%" "E:\Project\tietu-parenting\scripts\publish_story.py" --next --commit >> "%LOG%" 2>&1
set SRC=%errorlevel%
"%PY%" "E:\Project\tietu-parenting\scripts\tietu_queue.py" --style comic --limit %TIETU_COUNT% --commit >> "%LOG%" 2>&1
set TRC=%errorlevel%
echo [%date% %time%] end story_rc=%SRC% tietu_rc=%TRC% >> "%LOG%"
