@echo off
chcp 65001 >nul
rem daily drafts: newest story + tietu into the WeChat draft box. never publishes.
rem story: first story without a draft; tietu: first N tietu without a draft (comic style).
rem retries up to 3 attempts / 15 min apart, because WeChat rejects requests when the
rem outbound IP is not in the account whitelist (40164) and the IP can change between runs.
setlocal
cd /d "E:\Project\tietu-parenting"
if not exist "E:\Project\tietu-parenting\logs" mkdir "E:\Project\tietu-parenting\logs"
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
set TIETU_COUNT=3
set LOG=E:\Project\tietu-parenting\logs\daily-drafts.log
set ATTEMPT=0

:try
set /a ATTEMPT+=1
echo [%date% %time%] start attempt=%ATTEMPT% >> "%LOG%"
"%PY%" "E:\Project\tietu-parenting\scripts\publish_story.py" --next --commit >> "%LOG%" 2>&1
set SRC=%errorlevel%
"%PY%" "E:\Project\tietu-parenting\scripts\tietu_queue.py" --style comic --limit %TIETU_COUNT% --commit >> "%LOG%" 2>&1
set TRC=%errorlevel%
echo [%date% %time%] end attempt=%ATTEMPT% story_rc=%SRC% tietu_rc=%TRC% >> "%LOG%"

if %SRC%==0 if %TRC%==0 goto done
if %ATTEMPT% GEQ 3 goto done
echo [%date% %time%] retry in 15 min (经常是 IP 白名单 40164，换网后 IP 变了) >> "%LOG%"
ping -n 900 127.0.0.1 >nul
goto try

:done
exit /b 0
