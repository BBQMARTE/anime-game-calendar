@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "SDK=D:\Android\Sdk"
set "GRADLE_VER=9.6.1"
set "GRADLE_HOME=D:\Android\gradle-%GRADLE_VER%"
set "GRADLE_ZIP=D:\Android\gradle-%GRADLE_VER%-bin.zip"
set "PROJ=%~dp0android"

echo ============================================
echo   二游活动日历 - 安卓环境安装 + APK 构建
echo   SDK 目录: %SDK%
echo ============================================
echo.

echo [1/5] 写入 SDK 许可文件...
if not exist "%SDK%\licenses" mkdir "%SDK%\licenses"
(
echo 8933bad161af4178b1185d1a37fbf41ea5269c55
echo d56f5187479451eabf01fb78af6dfcb131a6481e
echo 24333f8a63b6825ea9c5514f83c2829b004d1fee
)>"%SDK%\licenses\android-sdk-license"

echo [2/5] 准备 Gradle %GRADLE_VER% ...
if not exist "%GRADLE_HOME%\bin\gradle.bat" (
  if not exist "%GRADLE_ZIP%" (
    echo      从腾讯云镜像下载 Gradle,约 140MB...
    curl -L --retry 3 -o "%GRADLE_ZIP%" "https://mirrors.cloud.tencent.com/gradle/gradle-%GRADLE_VER%-bin.zip"
    if errorlevel 1 (
      echo      镜像下载失败,改用官方源...
      curl -L --retry 3 -o "%GRADLE_ZIP%" "https://services.gradle.org/distributions/gradle-%GRADLE_VER%-bin.zip"
    )
  )
  echo      解压 Gradle...
  powershell -NoProfile -Command "Expand-Archive -LiteralPath '%GRADLE_ZIP%' -DestinationPath 'D:\Android' -Force"
)

echo [3/5] 配置工程...
>"%PROJ%\local.properties" echo sdk.dir=D:\\Android\\Sdk

echo [4/5] 准备正式签名密钥(仅首次生成,请务必备份)...
rem 密钥文件丢失但配置还在时,清掉配置回退 debug,避免构建报错
if exist "%PROJ%\keystore.properties" (
  if not exist "%PROJ%\ycal.keystore" del "%PROJ%\keystore.properties"
)
if not exist "%PROJ%\keystore.properties" (
  where keytool >nul 2>nul
  if errorlevel 1 (
    echo      未找到 keytool,本次将回退构建 debug APK
  ) else (
    keytool -genkeypair -keystore "%PROJ%\ycal.keystore" -alias ycal -keyalg RSA -keysize 2048 -validity 10950 -storepass ycal_release -keypass ycal_release -dname "CN=YCal, OU=Yoyuxi, O=Yoyuxi, C=CN"
    if errorlevel 1 (
      echo      密钥生成失败,本次将回退构建 debug APK
    ) else (
      >"%PROJ%\keystore.properties" (
        echo storeFile=ycal.keystore
        echo storePassword=ycal_release
        echo keyAlias=ycal
        echo keyPassword=ycal_release
      )
      echo      已生成 ycal.keystore 与 keystore.properties
    )
  )
)

echo [5/5] 构建 APK...
echo      首次构建会自动下载 Android SDK 组件与依赖,可能需要 5-15 分钟,请耐心等待
echo.
cd /d "%PROJ%"
set "APK_REL=%PROJ%\app\build\outputs\apk\release\app-release.apk"
set "APK_DBG=%PROJ%\app\build\outputs\apk\debug\app-debug.apk"
set "BUILT_REL=0"
if exist "%PROJ%\keystore.properties" (
  call "%GRADLE_HOME%\bin\gradle.bat" assembleRelease --no-daemon --console=plain
  if exist "%APK_REL%" set "BUILT_REL=1"
)
if "%BUILT_REL%"=="0" (
  echo      未配置正式签名或构建失败,回退构建 debug APK...
  if not exist "%APK_DBG%" call "%GRADLE_HOME%\bin\gradle.bat" assembleDebug --no-daemon --console=plain
)

echo.
if "%BUILT_REL%"=="1" (
  echo ============================================
  echo   构建成功! 正式签名 APK 位置:
  echo   %APK_REL%
  echo   传到手机安装即可(需允许安装未知来源应用^)
  echo   注意: android\ycal.keystore 请务必备份,丢失后无法覆盖升级
  echo ============================================
) else if exist "%APK_DBG%" (
  echo ============================================
  echo   已回退构建 debug APK(未配置正式签名^):
  echo   %APK_DBG%
  echo ============================================
) else (
  echo ============================================
  echo   构建失败,请把上方报错信息发给我排查
  echo ============================================
)
echo.
pause
