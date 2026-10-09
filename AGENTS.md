# linxira-completion-agent · Agent 开发规范

> **档位**:A 档 · 系统源仓(带 `VERSION` + `.github/workflows/release.yml`)。
> **本仓职责**:首次联网完成代理——展示安装回执(receipt)中**明确延后**的软件,并把已安装 catalog 绑定到该回执。
> 通用条款见工作区总纲 `f:\Linxira-OS\AGENTS.md`;发布/测试口径见 `linxira-os/docs/RELEASE_STANDARD.md`。本文件只写本仓特有约定。

## 职责与边界

- **负责**:从安装回执读取「明确延后」的软件条目,显示来源、大小、许可证、对软件仓库的影响以及是否可延后(deferability)。
- **不负责**:安装本身与事务执行(归 `linxira-components`);catalog 数据(归 `linxira-catalog`)。
- **安全边界**:
  - 经过审阅的官方 Arch 应用与组件应在**首次启动前**由 Calamares 装入目标;**若回执错误地把它们交给本代理,必须拒绝**。
  - `operation` 类叶子在其专用动作实现存在之前**保持延后**;AUR / Flatpak / Conda / 专有 / review 通道条目在其专用 provider 与 review 契约实现前**保持延后**。
  - 本代理**不接受任何包名、命令、URL 或仓库定义**。

## 目录布局

```
src/linxira_completion_agent/  app.py / model.py / selection.py
                               backend.py / state.py / about.py
data/                          org.linxira.Completion.desktop / .metainfo.xml
data/autostart/                org.linxira.Completion.desktop
tests/                         test_completion / test_about_metadata
```

## 本地校验

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

CI(`.github/workflows/ci.yml`,Python 3.13)即跑上述两条。

## 版本与发布

- 版本唯一来源是根目录 `VERSION`(当前 0.1.1);`pyproject.toml` version 必须同步。
- CLI 入口:`linxira-completion-agent = linxira_completion_agent.app:main`(依赖 `PySide6`,Python ≥ 3.11)。
- 提交 `VERSION` 变更即触发 `.github/workflows/release.yml` 走全自动发布链。**禁止手工 bump**。

## 禁区

- 不得让本代理承担安装/提权职责;所有安装走 `linxira-components` 的事务链。
- 不得接受包名 / 命令 / URL / 仓库定义作为输入。
- 不得把应在前置阶段安装的 reviewed Arch 条目「延后」处理——遇到这种回执要拒绝并显式报错。
- 破坏性操作先确认;不得提交密钥/凭据。