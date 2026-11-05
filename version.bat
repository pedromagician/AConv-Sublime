:: Sets _aconv_version to the version reported by AConv.exe
@SET _aconv_version=NOT INSTALLED
@IF NOT EXIST "%~dp0AConv.exe" GOTO:EOF
@PUSHD "%~dp0"
@FOR /F "tokens=1,2" %%A IN ('.\AConv.exe -help 2^>NUL') DO @IF /I "%%A"=="AConv" @SET "_aconv_version=v%%B" & GOTO aconv_version_done
:aconv_version_done
@POPD
