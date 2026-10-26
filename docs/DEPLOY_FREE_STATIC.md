# 卡卡 · AI 个性化饮食管理 Agent —— 简历展示站部署说明

本方案选择 **GitHub Pages（完全免费、无后端、无密钥）** 作为长期稳定的简历展示入口。
代码同时兼容 **Cloudflare Pages** 作为备选（如需更优国内访问可切换）。

---

## 一、为什么选择静态案例页

本项目的核心是「LangChain 智能体 + 外部大模型 + 数据库」的**交互式后端**。
它在免费 Serverless 平台（Cloudflare Pages / GitHub Pages / Vercel 免费层）上无法稳定承载，
因为免费层对函数冷启动、内存与超时（单次大模型推理可能耗时数十秒）均有严格限制。

因此本展示页采用**纯静态产品案例页**方案：
- 无后端、无数据库、无密钥写入前端或公开仓库；
- 全球可访问、长期免费、刷新不 404；
- 适配电脑与手机，适合放入个人简历。
- 想体验完整交互版，可下载源码在本地/Docker 主机运行（见仓库内 `docs/` 与 `scripts/`）。

---

## 二、最终公开网址

- **主站（GitHub Pages）**：`https://525-helen.github.io/HI/`
  （启用后自动生效，见下文"启用步骤"）
- **源码仓库**：`https://github.com/525-Helen/HI`

> 说明：最终网址与你的 GitHub 用户名绑定。因仓库名为 `HI`、用户名为 `525-Helen`，
> GitHub Pages 固定生成 `https://525-helen.github.io/HI/`（用户名会自动转为小写）。

---

## 三、启用步骤（要做的仅此一处）

代码与自动发布配置已全部就绪并提交。你只需在 GitHub 网页上做 **1 次设置**：

1. 打开仓库：`https://github.com/525-Helen/HI`
2. 点击顶部 **Settings（设置）**
3. 左侧菜单选择 **Pages（页面）**
4. 找到 **Build and deployment（构建和部署）→ Source（来源）**
5. 下拉框选择 **Deploy from a branch（从分支部署）**
6. 在 **Branch（分支）** 选择 `main`，在 **folder（目录）** 选择 `/docs`
7. 点击 **Save / 保存**
8. 等待 1~2 分钟发布完成，页面顶部会出现网址：`https://525-helen.github.io/HI/`，
   点击 **Visit site** 即可打开。

> 若想直接用无痕浏览器验证，请打开最终网址，确认：可正常打开、手机端无溢出、
> 无 404、页面源代码中不含任何密钥。

---

## 四、网站源文件 / 下载 ZIP

- 源文件位于本仓库 **`docs/`** 目录：`docs/index.html`（单文件，纯 HTML/CSS/JS，无外部依赖）。
- 下载 ZIP（无需登录）：打开仓库首页 `https://github.com/525-Helen/HI` →
  点击绿色 **Code → Download ZIP**，即可下载整个源码包。

---

## 五、部署平台及免费额度说明

| 平台 | 用途 | 免费额度 | 配额说明 |
|------|------|----------|----------|
| **GitHub Pages** | 主站（本方案） | 无限公开站点、无限带宽（组织/个人 1 GB 站点大小，页面<10MB/次） | 适合纯静态展示 |
| Cloudflare Pages | 备选 | 无限请求、免费 100 GB/月带宽、无构建数限制 | 适合需要更好国内/全球 CDN |
| Vercel | 备选 | Hobby 免费层：100 GB 带宽/月、函数 10s 超时 | 静态站足够 |

本项目采用 **GitHub Pages**，对纯静态页完全免费且无有效流量限制，最适合长期简历展示。

---

## 六、后续更新网站的方法

### 方式 A：直接在网页改（最快，无需本地环境）
1. 打开仓库 `https://github.com/525-Helen/HI` → 进入 `docs/index.html`
2. 点击右上角 ✏️（编辑）图标，在线修改文字/内容
3. 页面底部填写 Commit message（如 `update content`）→ 点击 **Commit changes**
4. 等待约 1~2 分钟，GitHub 自动将 `docs/` 更新发布，页面更新生效。

### 方式 B：本地改完推送
```bash
git clone https://github.com/525-Helen/HI.git
cd HI
# 修改 docs/index.html
git add docs/index.html
git commit -m "update website"
git push
```
推送 main 分支后，GitHub 自动将 `docs/` 目录更新发布。

---

## 七、Token / 密钥 / 凭据维护

- 本公开案例页为**纯静态站，不含任何 API Key / Token / PIN**（已明确要求，请勿在 `docs/` 中写入任何密钥）。
- 完整的交互式后端所用密钥（外部大模型 API Key、数据库连接串等）**仅存在于后端环境变量**中，
  **绝不写入前端代码或公开仓库**。
- 如需长期运行完整后端，推荐使用：
  - **SAT / OAuth** 等长期有效的鉴权方式；**不要**使用 24 小时失效的短期临时 Token。
  - 将密钥通过云平台 **环境变量 / Secret** 注入，而不是硬编码提交。
- 若密钥失效：只需更新后端服务所在平台的环境变量并重启服务，**本案例页无需任何改动**（因为它不涉及密钥）。

维护原则：**公开仓库 0 密钥**、**前端 0 密钥**、**密钥只在服务端环境变量**。

---

## 八、（备选）部署到 Cloudflare Pages

如需国内访问更优，可同样部署到 Cloudflare Pages（纯静态，无需 Key）：

1. 注册/登录 [Cloudflare](https://dash.cloudflare.com)
2. 进入 **Workers & Pages → Create → Pages → Connect to Git**
3. 授权连接 GitHub 的 `525-Helen/HI` 仓库
4. 构建配置：
   - **Build command**：留空（纯静态）
   - **Build output directory**：填写 `docs`
5. 点击 **Save and Deploy**
6. 完成后得到形如 `https://<project>.pages.dev` 的免费长期网址。

---

## 安全说明

本站点与其部署方案遵守以下原则：
- 任何人无需登录即可访问，但**不暴露任何用户数据、密钥或敏感配置**；
- 刷新任意路径不会出现 404；
- 移动端与电脑端自适应，无横向溢出。