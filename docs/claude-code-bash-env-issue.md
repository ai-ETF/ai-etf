# Claude Code 在 WSL 环境下的 Bash 工具问题

> 使用 Claude Code（Windows 桌面版）开发 WSL 项目时，Bash 工具无法调用 WSL 中安装的工具（如 poetry、pip、python）。

---

## 问题现象

在 WSL 终端中正常使用 poetry：

```bash
sing@singLevon:~/smartAnalysisOfETF/ai-etf$ poetry --version
Poetry (version 2.2.1)
```

但在 Claude Code 的 Bash 工具中执行同样的命令：

```bash
$ poetry --version
/usr/bin/bash: line 1: poetry: command not found
```

---

## 根因分析

Claude Code **Windows 桌面版**的 Bash 工具使用的是 **Git Bash（MSYS2）**，而不是 WSL。

验证方法：

```bash
# 在 Claude Code 的 Bash 中执行
$ echo $PATH
```

输出结果包含 `/mingw64/bin`、`/c/Users/sing` 等 Windows 路径，说明当前 shell 是 Git Bash，不是 Linux。

```bash
$ cat /etc/passwd
cat: /etc/passwd: No such file or directory
```

WSL 中应该有这个文件，找不到说明不在 WSL 环境。

**本质是两个隔离的运行时：**

| | Claude Code Bash | WSL 终端 |
|---|---|---|
| Shell | Git Bash (MSYS2) | Bash (Ubuntu 20.04) |
| PATH | Windows 路径 | Linux 路径 |
| 安装的工具 | Windows 侧的 git、node 等 | poetry、pip、python 等 |
| 文件系统 | 可访问 WSL 文件（通过 `/mnt/`） | 原生 Linux 文件系统 |

---

## 影响范围

### 受影响的操作

- `poetry`、`pip`、`python` 等 WSL 环境中的 CLI 工具
- 依赖 WSL 环境的包管理操作（`poetry add`、`pip install`）
- WSL 中的虚拟环境相关命令

### 不受影响的操作

- **文件读写**：Read、Write、Edit 工具直接访问文件系统，不受 shell 环境影响
- **Git 命令**：Windows 侧通常也装了 git，Git Bash 中可正常使用
- **简单的文件操作**：`ls`、`mkdir`、`cp` 等基础命令在 Git Bash 中可用

---

## 解决方案

### 方案一：在 Claude Code 中用 `!` 前缀（推荐）

在 Claude Code 的输入框中，用 `!` 前缀可以将命令发送到本地 shell（即 WSL）：

```
! poetry add akshare
! pip install -r requirements.txt
! python test_qa.py
```

### 方案二：在另一个 WSL 终端窗口手动执行

打开一个新的 WSL 终端，`cd` 到项目目录，手动执行命令。

### 方案三：让 Claude Code 提示用户手动操作

当 Claude Code 需要执行 WSL 命令时，输出命令让用户自己跑，而不是直接用 Bash 工具。

---

## 快速判断指南

当你不确定某个命令该在哪个环境执行时：

```
需要 poetry / pip / python？  →  用 ! 前缀 或 WSL 终端
需要 git / ls / mkdir？       →  Claude Code Bash 可以
需要读写文件？               →  Read/Write/Edit 工具，无影响
```

---

## 为什么文件读写没问题？

Claude Code 的 Read、Write、Edit 工具是通过 Node.js 的文件系统 API 直接访问磁盘的，路径 `\\wsl.localhost\Ubuntu-20.04\...` 在 Windows 上是一个有效的 UNC 路径，所以不经过 shell，不受 Git Bash 环境限制。
