@echo off
setlocal EnableExtensions
title AttendIQ Setup
echo ==================================================
echo   AttendIQ - One-click setup
echo ==================================================
echo.

rem ---- 1. Locate the Desktop (works even if OneDrive moves it)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
set "TARGET=%DESKTOP%\AttendIQ"
set "SRC=%~dp0"

if not exist "%SRC%app.py" (
    echo [ERROR] app.py was not found next to this setup file.
    echo Extract the whole ZIP first, then run Setup_AttendIQ.bat again.
    pause
    exit /b 1
)

rem ---- 2. Find Python
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python was not found on this computer.
    where winget >nul 2>nul
    if not errorlevel 1 (
        echo Trying to install Python 3.12 using winget...
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        echo.
        echo If the install succeeded, CLOSE this window and run Setup_AttendIQ.bat again.
    ) else (
        echo Please install Python 3.10 - 3.12 from https://www.python.org/downloads/
        echo IMPORTANT: tick "Add python.exe to PATH" during install, then run this setup again.
        start https://www.python.org/downloads/
    )
    pause
    exit /b 1
)
echo Using Python: %PY%
%PY% --version

rem ---- 3. Create the project folder and copy files
echo.
echo Creating folder: %TARGET%
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%SRC%app.py" "%TARGET%\app.py" >nul
copy /Y "%SRC%requirements.txt" "%TARGET%\requirements.txt" >nul
if exist "%SRC%README.txt" copy /Y "%SRC%README.txt" "%TARGET%\README.txt" >nul

rem ---- 4. Streamlit settings (skips the first-run email prompt)
if not exist "%TARGET%\.streamlit" mkdir "%TARGET%\.streamlit"
> "%TARGET%\.streamlit\config.toml" (
    echo [browser]
    echo gatherUsageStats = false
)
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    > "%USERPROFILE%\.streamlit\credentials.toml" (
        echo [general]
        echo email = ""
    )
)

rem ---- 5. Virtual environment and dependencies (needs internet once)
echo.
echo Creating virtual environment...
%PY% -m venv "%TARGET%\venv"
if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
)
echo Installing libraries. This can take 2-5 minutes...
"%TARGET%\venv\Scripts\python.exe" -m pip install --upgrade pip
"%TARGET%\venv\Scripts\python.exe" -m pip install -r "%TARGET%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Library installation failed. Check the internet connection and run setup again.
    pause
    exit /b 1
)
"%TARGET%\venv\Scripts\python.exe" -c "import streamlit, pandas, numpy, plotly, sklearn; print('All libraries OK')"
if errorlevel 1 (
    echo [ERROR] Libraries did not import correctly.
    pause
    exit /b 1
)

rem ---- 6. Launcher + Desktop shortcut
> "%TARGET%\Run_AttendIQ.bat" (
    echo @echo off
    echo title AttendIQ - keep this window open while presenting
    echo cd /d "%%~dp0"
    echo "%%~dp0venv\Scripts\python.exe" -m streamlit run app.py
    echo pause
)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP%\AttendIQ.lnk');$s.TargetPath='%TARGET%\Run_AttendIQ.bat';$s.WorkingDirectory='%TARGET%';$s.Save()"

echo.
echo ==================================================
echo   Setup complete.
echo   Folder   : %TARGET%
echo   To start : double-click "AttendIQ" on the Desktop
echo   Admin password: admin
echo ==================================================
echo.
choice /c YN /m "Start AttendIQ now"
if errorlevel 2 exit /b 0
start "" "%TARGET%\Run_AttendIQ.bat"
exit /b 0
