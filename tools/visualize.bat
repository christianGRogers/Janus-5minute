@echo off
REM Quick visualization script for Janus Bot performance data (Windows)
REM Usage: visualize.bat <csv_file> [output_dir]

setlocal enabledelayedexpansion

set "CSV_FILE=%1"
set "OUTPUT_DIR=%2"

if not defined OUTPUT_DIR set "OUTPUT_DIR=.\charts"

if not defined CSV_FILE (
    echo.
    echo Error: CSV file not specified
    echo.
    echo Usage:
    echo   visualize.bat ^<csv_file^> [output_dir]
    echo.
    echo Examples:
    echo   visualize.bat market_performance.csv
    echo   visualize.bat ..\logs\markets\2026-04-23_22-15-45\market_performance.csv
    echo   visualize.bat market_performance.csv .\my_charts
    echo.
    exit /b 1
)

if not exist "!CSV_FILE!" (
    echo Error: File not found: !CSV_FILE!
    exit /b 1
)

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Check if requirements are installed
echo Checking dependencies...
python -c "import pandas, matplotlib, seaborn" >nul 2>&1
if errorlevel 1 (
    echo Installing missing dependencies...
    pip install -r requirements-analysis.txt
    if errorlevel 1 (
        echo Error: Failed to install dependencies
        exit /b 1
    )
)

REM Run visualization
echo.
echo Running visualization tool...
echo Input:  !CSV_FILE!
echo Output: !OUTPUT_DIR!
echo.

python visualize_performance.py "!CSV_FILE!" --output "!OUTPUT_DIR!"

if errorlevel 1 (
    echo.
    echo Error: Visualization failed
    exit /b 1
)

echo.
echo Success! Charts saved to: !OUTPUT_DIR!
echo.

REM Try to open output directory
if exist "!OUTPUT_DIR!" (
    start "!OUTPUT_DIR!"
)

endlocal
