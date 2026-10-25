# 卡卡 · AI 饮食管家 — 静态案例站部署与维护说明

> 本案例页为**纯静态**产品展示站点，部署在 **GitHub Pages**，用于个人简历长期稳定展示。
> 无后端依赖、无数据库调用、无任何密钥/Token 暴露，刷新不 404，电脑/手机自适应。

---

## 一、最终公开网址

**https://525-helen.github.io/HI/**

（若你尚未在 Settings → Pages 中开启，请按下方"如何启用"操作后生效）

---

## 二、如何启用 GitHub Pages（一次性操作）

1. 打开仓库：`https://github.com/525-Helen/HI`
2. 点击 **Settings**（设置）
3. 左侧栏下拉找到 **Pages**
4. **Source** 选择 **`Deploy from a branch`**
5. **Branch** 选择 **`gh-pages`**，文件夹选 **`/ (root)`**
6. 点击 **Save**
7. 等待 1~3 分钟，网址即生效：`https://525-helen.github.io/HI/`

> `gh-pages` 分支已由作者推送完毕，里面只包含案例页 `index.html`（根目录），不含任何业务代码与密钥。

---

## 三、网站源文件

- 案例页源文件（单文件，自包含 CSS/HTML，无外部依赖）：
  - `portfolio/index.html`（同目录，见仓库 `main` 分支）
- 可下载 ZIP：在仓库页面点击右上角 **Code → Download ZIP**，或直接访问：
  - `https://github.com/525-Helen/HI/archive/refs/heads/gh-pages.zip`（= 网站可部署副本）
  - `https://github.com/525-Helen/HI/archive/refs/heads/main.zip`（= 完整项目源码）

---

## 四、部署平台及免费额度说明

| 项目 | 说明 |
|------|------|
| 平台 | **GitHub Pages**（微软旗下，永久免费） |
| 免费额度 | 站点公开即免费；每月约 **100GB** 带宽、约 **1GB** 站点存储，远超本案例页所需（仅 16KB）。**无过期时间**，适合长期简历展示 |
| 域名 | 默认 `https://<用户名>.github.io/<仓库名>/`，长期有效 |
| HTTPS | GitHub Pages 自动签发并维护免费 SSL 证书，无需手动配置 |

> 如需更方便的记忆域名，可在 Settings → Pages → "Custom domain" 绑定自有域名（需另行购买域名，非必需）。

---

## 五、后续更新网站的方法

本案例页是**自己动手、可视化修改**的，方法有两种：

### 方法 A：在线直接改（推荐，无需本地环境）
1. 打开仓库，点击顶部 **`gh-pages`** 分支（分支下拉框选 `gh-pages`）
2. 点击 `index.html` → 点右上角 **铅笔图标（编辑）**
3. 修改文字/图片/样式后，点 **Commit changes**（提交）
4. 等 1~2 分钟，刷新网址即可看到更新

### 方法 B：本地改完重新推送
```bash
# 修改 portfolio/index.html 后，同步到 gh-pages 分支
git checkout gh-pages
cp portfolio/index.html index.html
git add index.html
git commit -m "update portfolio"
git push origin gh-pages
git checkout main
```

> GitHub Pages 是全自动流水线：向 `gh-pages` 分支推送修改，会自动重新构建并发布新版本。

---

## 六、Token 更新或失效时的维护方法

本案例页为**纯静态页面，不包含任何接口调用或前端密钥**，因此：

- **不存在因 Token 失效而导致页面不可用的问题**。
- 你在本案例页**看不到任何 API Key / Token / 密钥**（已通过无痕浏览器验证 + 源码 grep 双重确认）。

> 说明：项目中确实存在部署 `main` 分支代码所需的凭据（如外部大模型 Key、数据库地址等），但这些**仅用于后端 Agent 运行**，与这个简历展示站完全隔离。本案例页交付物（`gh-pages` 分支）只含静态 HTML，无需任何维护。

---

## 七、常见问题

**Q：改了 gh-pages 分支，为什么网址没变化？**
A：GitHub Pages 发布有 1~3 分钟延迟，稍等后强制刷新（Ctrl/Cmd+Shift+R）。

**Q：网址打不开 / 404？**
A：请确认 Settings → Pages → Source 已选 `Deploy from a branch` + `gh-pages` + `/ (root)`，并已点 Save。

**Q：刷新深链接会 404 吗？**
A：本案例页是单页应用，滚动定位不改变 URL 路径，全部内容都在 `/` 一个页面内，**刷新永不 404**。

**Q：手机上看会变形吗？**
A：页面为响应式设计，已适配 320px 起的手机与桌面端，无横向溢出。

---

_本文档由部署流程自动生成，随案例页一同维护。_