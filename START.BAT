@echo off
set REPO=C:\github\KajovoPasport
call "%REPO%\.venv\Scripts\activate.bat"
pushd "%REPO%"
python -m KajovoPasport
popd
