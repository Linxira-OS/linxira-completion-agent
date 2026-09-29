# Linxira Completion Agent

The Completion Agent presents explicitly deferred software from an installer
receipt. It binds the installed catalog to that receipt and displays source,
size, license, repository impact, and deferability.

Reviewed official Arch applications and components are installed into the
Calamares target before first boot and are rejected if a receipt incorrectly
hands them to Completion. Operation leaves remain deferred until their dedicated
action implementation exists.
The agent accepts no package names, commands, URLs, or repository definitions.
AUR, Flatpak, Conda, proprietary, and review-channel items remain deferred until
their dedicated providers and review contracts are implemented.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

---

## 简体中文

Completion Agent 展示安装回执中明确延后的软件。它将已安装目录绑定到该回执，
并显示来源、大小、许可证、对软件仓库的影响，以及是否可延后。

经过审阅的官方 Arch 应用与组件会在首次启动前安装进 Calamares 目标环境；如果
回执错误地把它们交给 Completion，会被拒绝。操作类条目在其专用动作实现存在
之前保持延后状态。
本代理不接受任何软件包名、命令、URL 或仓库定义。AUR、Flatpak、Conda、专有
软件以及审阅渠道条目在其专用提供者和审阅契约实现之前保持延后状态。

### 开发

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```
