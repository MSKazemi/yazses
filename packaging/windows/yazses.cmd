@echo off
rem Console shim so `yazses <command>` works from cmd and PowerShell.
rem
rem The bundle's CLI binary is named yazses-cli.exe because the windowed
rem binary already occupies YazSes.exe, and Windows filenames are
rem case-insensitive — "yazses.exe" and "YazSes.exe" cannot coexist in one
rem directory. %~dp0 keeps this working regardless of install location.
"%~dp0yazses-cli.exe" %*
exit /b %ERRORLEVEL%
