@echo off
rem Console shim so `yazses <command>` works from cmd and PowerShell.
rem
rem The bundle's CLI binary is yazses-cli.exe, never yazses.exe: Windows tries
rem .exe before .cmd (PATHEXT) and ignores case, so any yazses.exe in this
rem folder would answer to `yazses` instead of this shim. That is what the
rem windowed app did while it was called YazSes.exe; it is YazSesApp.exe since
rem v2.20.0. %~dp0 keeps this working regardless of install location.
"%~dp0yazses-cli.exe" %*
exit /b %ERRORLEVEL%
