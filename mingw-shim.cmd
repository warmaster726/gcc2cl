@echo off
rem Place this file in a directory that appears before MinGW in PATH.
rem Make copies named gcc.cmd, g++.cmd, and the MinGW target-prefixed names.
set "GCC2CL_HOME=%~dp0"
py "%GCC2CL_HOME%gcc2cl.py" --compiler "%~n0" -- %*
exit /b %ERRORLEVEL%
