# 第 1 步：环境检查（本地）

用于首次使用或出现环境类报错时。正常运行状态下**不要读本文件**。

## 三件套一键体检

```bash
command -v sshpass
stat -c '%a %n' ~/.ssh/47.113.220.182.pass ~/.ssh
```

## 通过标准

| 检查项 | 要求 |
|--------|------|
| sshpass | 已安装（有路径输出） |
| 密码文件 `~/.ssh/47.113.220.182.pass` | 存在且权限 `600` |
| `~/.ssh` 目录 | 权限 `700` |

## 失败处理

- **sshpass 缺失** → 安装：
  ```bash
  command -v sshpass >/dev/null || sudo apt-get install -y sshpass
  ```
- **密码文件缺失** → **向用户索要密码**，写入 `~/.ssh/47.113.220.182.pass` 后 `chmod 600`。绝不硬编码密码。
- **权限不对** → 修正：
  ```bash
  chmod 600 ~/.ssh/47.113.220.182.pass && chmod 700 ~/.ssh
  ```

✅ 全部通过 → 进入[第 2 步：连接测试](./connect.md)
