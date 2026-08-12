@echo off
@if "%AI_TEAM_OS_LLVM_BIN%"=="" exit /b 2
"%AI_TEAM_OS_LLVM_BIN%\clang.exe" --driver-mode=cl %*
