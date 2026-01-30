@echo off
set  REPO=C:\GitHub\KajovoPasport
call %REPO%\.venv\Scripts\activate.bat
pushd %REPO%
python -m KajovoPasport
popd
