@echo off
setlocal

set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%"

if exist "%LocalAppData%\Programs\Python\Python314\Scripts\shub.exe" (
    "%LocalAppData%\Programs\Python\Python314\Scripts\shub.exe" deploy
) else (
    shub deploy
)

popd
endlocal