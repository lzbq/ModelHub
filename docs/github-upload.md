# ModelHub 上传 GitHub

核对日期：2026-09-23。

建议使用一个仓库管理 `token-java`、`token-agent`、`token-web`、文档和初始化 SQL。提交源代码与依赖清单；Python 虚拟环境、node_modules、构建产物、运行数据库、日志和真实 .env 留在本地。

## 当前目录需要注意的两点

- 根目录 `.git` 是空目录，尚不是有效仓库。
- `token-agent/.git` 是独立旧仓库，且 `.env` 已被提交到它的历史中。只补 `.gitignore` 不会清除旧历史里的文件。下面的步骤把旧 Git 元数据保留为本地备份，建立全新根仓库，不导入旧提交。

旧仓库仍含原有历史。若曾把真实凭证推送到远端或提供给别人，需要撤销或轮换相应凭证；新建仓库不会清除旧远端的记录。

## 1. 检查准备好的文件

根 `.gitignore` 已忽略 `.env`、Python 虚拟环境、node_modules、target、dist、日志、IDE 文件、运行数据和 `.git-backups`，保留 `.env.example`、依赖清单、源码、测试、文档和 SQL。

`token-agent/.agents/skills` 是 Agent 启动时加载的工作流，必须提交。不要全局忽略所有 `.agents` 目录。

Java YAML 中的数据库默认密码已移至本地 `token-java/.env`，模板为 `token-java/.env.example`。提交前仍应确认 YAML、Compose、SQL、脚本、文档及截图没有其他真实密码、业务数据或用户信息。

## 2. 备份子仓库并初始化根仓库

在 PowerShell 中先预览：

```powershell
Set-Location 'D:\python\ModelHub'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\prepare-github.ps1
```

执行本地准备：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\prepare-github.ps1 -Apply
```

脚本会检查路径、拒绝链接目录与已有根仓库，把各子项目的 `.git` 移到根目录下 `.git-backups/<随机批次>/`，然后执行 `git init -b main` 并检查敏感文件忽略规则。它不会删除源码、暂存、提交或推送，也不会修改系统执行策略。

这会让三个子项目由根仓库统一管理。旧 Agent 提交仍保留在备份中，不属于新仓库的历史。执行成功后不要再次运行准备脚本；日常更新只需要 `git add`、`git commit`、`git push`。

如中途失败，脚本不会自动回滚；已经移动的 Git 元数据仍在输出所示备份路径，源码保留。初始化完成前需要恢复旧 Agent 仓库时，可在确认 `token-agent/.git` 不存在后，将备份中的 `token-agent.git` 移回该位置。不要把备份加入新仓库。

## 3. 检查候选文件并创建首次提交

```powershell
git status --short
git check-ignore -v token-agent/.env token-java/.env .git-backups/
git add --dry-run .
```

确认候选文件不包含 `.env`、虚拟环境、node_modules、日志、备份和构建产物，再暂存：

```powershell
git add .
git diff --cached --stat
git diff --cached --name-only
git ls-files --stage token-agent
```

`token-agent` 应展示普通源文件，不能只出现模式为 `160000` 的目录记录（那是嵌套仓库引用）。`token-agent/.agents/skills` 和两个 `.env.example` 应被保留。

配置本仓库的提交身份，替换为自己的信息；邮箱可以使用 GitHub 邮箱设置页提供的 noreply 地址：

```powershell
git config user.name '你的 GitHub 用户名'
git config user.email '你的 GitHub 提交邮箱'
git commit -m "Initial commit: ModelHub backend, agent and frontend"
```

## 4. 在 GitHub 创建空仓库并推送

访问 https://github.com/new，仓库名填写 `ModelHub`，选择所需的可见性。创建时不要初始化 README、.gitignore 或 License，因为本地已准备首次提交。

把下面的地址换成新仓库地址：

```powershell
git remote add origin https://github.com/YOUR_USERNAME/ModelHub.git
git push -u origin main
```

若 Git 提示登录，完成 Git Credential Manager 的浏览器授权。若终端要求 HTTPS 密码，使用适当权限的 GitHub Personal Access Token；不要把 Token 写进远程 URL、脚本或仓库。

推送后在 GitHub 确认三个源码目录和 README 都能打开，`.env` 与 `.git-backups` 不存在。不要直接拖拽上传整个 1.21 GB 文件夹或包含 .env 的压缩包。

## 5. 后续更新

在根目录执行：

```powershell
git status --short
git add .
git diff --cached --stat
git commit -m "Describe your changes"
git push
```

另一个电脑克隆后，重新安装依赖：前端 `npm ci`，Java 使用 Maven，Agent 创建虚拟环境后 `pip install -r requirements.txt`。从模板创建本地 `.env` 并填写自己的凭证，不需要提交本机的依赖目录。

## 官方说明

- [将本地源码加入 GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
- [从仓库中移除敏感数据](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
