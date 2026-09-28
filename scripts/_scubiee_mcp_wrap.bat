@echo off
echo ==== WRAP START %DATE% %TIME% >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
echo cwd=%CD% >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
echo args=%* >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
set >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
echo ==== ENV END >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
"C:\Users\usman\.local\bin\scubiee-mcp.EXE" %*
set RC=%ERRORLEVEL%
echo ==== WRAP EXIT rc=%RC% %TIME% >> "%USERPROFILE%\.scubiee\kiro_mcp_wrap.log"
exit /b %RC%
