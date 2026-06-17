# 部署为团队可访问网页

本项目是 Streamlit 应用，不能直接用 GitHub Pages 托管。推荐方式是：

```text
GitHub 仓库存代码 → Streamlit Community Cloud 部署 → 团队成员浏览器访问
```

> 重要提示：当前仓库只适合放演示数据或公开数据。真实 Wind 数据、客户数据、产品持仓、赎回信息、内部月报等不要上传到公网仓库或 Streamlit Community Cloud。

## 1. 上传到 GitHub

### 方法 A：网页上传，最简单

1. 打开 GitHub，新建仓库，例如 `macro_signal_dashboard`。
2. 建议先选择 `Private`。
3. 点击 `Add file` → `Upload files`。
4. 把本项目文件夹里的所有文件拖进去。
5. 点击 `Commit changes`。

仓库根目录应当能直接看到：

```text
app.py
requirements.txt
src/
data/
.streamlit/
README.md
DEPLOYMENT.md
```

不要上传外层 zip 包本身，也不要让仓库根目录变成 `macro_signal_dashboard/macro_signal_dashboard/app.py` 的双层结构。

### 方法 B：命令行上传

```bash
git init
git add .
git commit -m "Initial macro signal dashboard"
git branch -M main
git remote add origin https://github.com/<你的用户名>/macro_signal_dashboard.git
git push -u origin main
```

## 2. Streamlit Community Cloud 部署

1. 打开 Streamlit Community Cloud。
2. 用 GitHub 账号登录。
3. 点击 `New app`。
4. 选择你的 GitHub repo。
5. Branch 选择 `main`。
6. Main file path 填：

```text
app.py
```

7. 点击 `Deploy`。

部署成功后会得到一个类似下面的网页链接：

```text
https://你的项目名.streamlit.app
```

团队成员用浏览器打开这个链接即可，不需要安装 Python。

## 3. 后续更新方式

本地修改代码或数据后，只需要提交到 GitHub：

```bash
git add .
git commit -m "Update dashboard"
git push
```

Streamlit Cloud 会自动重新部署。

如果用 GitHub 网页上传，则直接在网页里替换文件并 Commit。

## 4. 正式内网部署建议

如果将来接入真实业务数据，更推荐：

```text
GitHub/GitLab 存代码
公司内网服务器运行 Streamlit
团队通过内网地址访问
```

例如：

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

团队访问：

```text
http://服务器内网IP:8501
```

这种方式更适合投后、FOF、客户信息、持仓、赎回测算等内部数据场景。
