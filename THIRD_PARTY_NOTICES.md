# 第三方组件说明

Windows 下载包包含 licenses/ 和 DEPENDENCIES.json，保留第三方组件原始许可证与版本清单。项目自身源码尚未指定开源许可证，第三方许可证不受影响。

本次构建使用 Python 3.12.8、mitmproxy 12.3.0、mitmproxy_rs / mitmproxy-windows 0.12.15、pydivert 3.1.3、httpx 0.28.1、PyInstaller 6.22.3，以及 Tk 和相关运行依赖。可选网站后端和机器人插件依赖不等于全部进入助手运行包；DEPENDENCIES.json 记录的是构建环境版本。

Windows 重定向组件、WinDivert 和 pydivert 涉及 LGPL 许可。Release 同时提供对应的 mitmproxy_rs v0.12.15、WinDivert v2.2.2、pydivert v3.1.3 源码，Rust Cargo.lock 锁定的依赖源码，以及 Python 依赖源文件和重建说明。原组件未修改。程序不限制替换这些组件，或为调试其修改而进行的逆向工程。重定向 EXE 和 WinDivert DLL/驱动保持独立文件，Python 部分可从源码重新打包。

完整许可文本以下载包 licenses/ 和上游源码中的 LICENSE/COPYING/NOTICE 为准。本说明不替代原始条款。本项目不是电费运营方、微信或 AstrBot 的官方产品。
