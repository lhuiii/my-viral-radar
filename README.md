# 📡 爆款雷达 · 网页版(不用碰终端)

每周自动抓竞对 IG 爆款 → 转录口播 → AI 拆解 → **改写成你自己语气的口播稿** → 生成可拖拽管理的 dashboard。

**这个版本全程在网页上点鼠标就能装好,不用打任何指令。** 照下面 6 步走,约 20 分钟。

---

## 开始前:准备 4 个账号(建议课前先建好)

- **GitHub**(github.com)— 免费,存代码 + 每周自动运行
- **Supabase**(supabase.com)— 免费,数据库。注册时选 *Continue with GitHub* 最快
- **Google AI Studio**(aistudio.google.com)— 免费,用 Google 账号登录就行。给 AI 拆解 + 我的稿用的 Gemini 钥匙
- **Apify**(apify.com)— 唯一收费,约 $5/月,负责抓 IG

---

## 第 1 步 · 复制这个模板到你的账号

1. 回到这个仓库最上面,点绿色按钮 **「Use this template」→「Create a new repository」**
2. Repository name 填你想要的名字(例:`my-viral-radar`)
3. 选 **Public**(免费版要公开才能出网页)
4. 点 **Create repository**

✅ 几秒钟你就有了一份自己的副本,全程鼠标,没碰终端。

---

## 第 2 步 · 建 Supabase 数据库

1. 到 supabase.com → **New project**(Region 选 Singapore,数据库密码自己存好)
2. 左边点 **SQL Editor** → New query
3. 打开你仓库里的 `schema.sql`,**整段复制**贴进去
4. **全篇只改最底下这 5 行**,换成你要追踪的竞对 IG 账号:

   ```sql
   insert into competitors (username, tracker, active) values
     ('换成竞对1', 'IG', true),
     ('换成竞对2', 'IG', true),
     ('换成竞对3', 'IG', true),
     ('换成竞对4', 'IG', true),
     ('换成竞对5', 'IG', true)
   on conflict do nothing;
   ```

   ⚠️ **只要账号名**,不要 `@`,不要链接。填 `nike` 对,填 `@nike` 或 `instagram.com/nike` 抓不到。

5. 点 **Run**,看到 Success
6. 左边点 **Table Editor**,确认 `posts` 和 `competitors` 两张表都在,`competitors` 里是你的 5 个竞对、`active` 都打了勾

> 💡 **8–15 个竞对**才撑得起一个每周有东西看的看板。想多加就复制上面任意一行、改账号名。

> ✅ 这段可以安全重复跑 —— 不会删任何数据,也不会产生重复竞对。以后要加竞对,跑 `加竞对.sql` 那一小段,或到 Table Editor 直接加行。

> ⚠️ 里面「安全锁」那段不要删减——公开钥匙只能读数据、改状态,删不掉你的数据。

---

## 第 3 步 · 复制 3 把 Supabase 钥匙

Supabase 左下角 **Settings → API Keys**,复制三样(先放记事本):

| 名字 | 长这样 |
|---|---|
| Project URL | `https://xxxx.supabase.co` |
| **Publishable key** | `sb_publishable_` 开头 |
| **Secret key** | `sb_secret_` 开头(**私密**,只进下一步的 Secrets)|

---

## 第 4 步 · 在你的仓库填钥匙和名字(网页操作)

到**你的仓库** → **Settings** → 左边 **Secrets and variables** → **Actions**。

**先点 Secrets 分页,New repository secret,加这 5 个**(名字要一模一样):

| Secret 名字 | 值 |
|---|---|
| `SUPABASE_URL` | 第 3 步的 Project URL |
| `SUPABASE_ANON_KEY` | 第 3 步的 **publishable key**(变量名没改)|
| `SUPABASE_SERVICE_ROLE_KEY` | 第 3 步的 **secret key**(变量名没改)|
| `APIFY_TOKEN` | Apify → Settings → API & Integrations 里的 token |
| `GEMINI_API_KEY` | aistudio.google.com → 左边 **Get API key** → **Create API key** → 复制(`AIza` 开头,免费) |

> `GEMINI_API_KEY` 是 AI 拆解和「我的稿」用的。免费档每天有次数上限,这个系统一周只用一百来次,够用;用完了隔天自动补。
>
> 可选第 6 个:`ANTHROPIC_API_KEY`(Claude 的 API key,付费)。设了就优先用 Claude,质量更好、不受免费额度限制;没设就用 Gemini。

**再点 Variables 分页,New repository variable,加这 3 个:**

| Variable 名字 | 值(例) |
|---|---|
| `BRAND` | 你系统的名字,例:`Yoga Radar` |
| `NICHE` | 你的领域,例:`瑜伽教练课程`(决定 AI 拆解方向) |
| `SYNC_DAY` | 例:`每周一`(显示在网页页脚) |

> 贴进网页输入框不会像终端那样贴烂,放心贴。

---

## 第 5 步 · 开网页(GitHub Pages)

到**你的仓库** → **Settings** → 左边 **Pages**:

- Source 选 **Deploy from a branch**
- Branch 选 **main**,文件夹选 **/docs**,点 **Save**

（现在 `docs/` 还没生成,先这样设着,跑完第 6 步网页就会出来。）

---

## 第 6 步 · 首次运行

1. 到**你的仓库** → **Actions** 分页,如果看到提示就点 **「I understand my workflows, enable them」**
2. 左边点 **Sync Content** → 右边 **Run workflow** → 绿色 Run workflow
3. 等它跑完(几分钟)。之后会自动接力:转录 → AI 拆解 → 生成网页,整个首跑大约 **20-60 分钟**,去忙别的就好
4. 全部跑完后,打开你的网址:**`https://<你的用户名>.github.io/<仓库名>/`**

✅ 看到爆款卡片、能播放、能拖拽改状态 = 成功。手机也能开,改状态不用密码。

---

## 装好之后

- 📅 每周一自动更新(想改时间:编辑 `.github/workflows/sync.yml` 里的 cron 那行)
- 🎬 每张卡片有 **我的稿** 按钮:AI 已经把这条爆款改写成**你的语气**的口播稿,点一下复制就能拍(怎么调语气见下面)
- ➕ 加/停竞对:Supabase → Table Editor → `competitors` 表加一行(active 打勾)或取消勾
- 🤖 系统每周自动推荐相关账号进 competitors(active 未勾),觉得好就勾
- 💰 费用:Apify 免费方案每月自带 $5 额度(不用绑卡),7 个竞对实测约 $1.1/月,一般用不完

## ➕ 在网页上加 / 停竞对(管理竞对)

不想进 Supabase,团队可以直接在爆款雷达页面顶部点 **管理竞对**:选 Instagram 或 Facebook,贴账号名或链接(**可以一次贴好几个**,用逗号、空格隔开),点添加;现有竞对旁边有「停止追踪 / 恢复」按钮(历史数据保留)。暂停 / 恢复**马上生效**,页面上该账号的帖子立刻隐藏 / 出现,不用等重新部署。每个账号旁边还会显示上次抓取的结果(几条、或「抓取失败:名字拼错 / 不是公开主页」)。

**第一次要做一次设置:**

1. Supabase → SQL Editor → New query,把仓库里 `admin_competitors.sql` 整段粘贴
2. 把最底下 `'换成你的口令'` 改成**你们团队的口令**(至少 8 个字符),点 Run。没改会报错、整段不生效,改完重跑即可
3. 把口令告诉团队。每个人第一次在页面「管理竞对」里输入一次,之后这台电脑的浏览器会记住

**为什么要口令:** 页面是公开的,每个竞对每周都会花 Apify 的钱。所以加 / 停竞对必须带口令,网页也不能直接读写 `competitors` 表,只能调用几个受限函数。口令只存哈希;连续输错 8 次锁定 10 分钟(按访问者 IP 分开记,别人乱试不会把你们团队锁在外面);活跃竞对默认最多 30 个(想改:`update app_settings set value = '40' where key = 'max_active_competitors';`)。

**加了之后自动只抓新账号:** 在网页点「添加」的当下,系统会通知 GitHub 马上跑一次 Sync Content,而且只抓**数据库里还没有帖子的账号**(就是刚加的),已有的账号一个都不碰,不花 Apify 的钱。一次加好几个时只通知一次。抓完后转录、AI 拆解、更新网页会接着自动跑,面板里会显示进度,跑完点「刷新页面」就能看到新帖子。没有视频要转录时(例如只加了 Facebook 页面)会自动跳过又大又慢的 Whisper 安装,更快跑完。

**每周一的自动抓取照旧,但更省钱:** 新账号第一次抓完整 60 天(最多 50 条);已经有数据的账号每周只回看最近 21 天(最多 25 条)就够,新帖子和最新的赞 / 评论数都抓得到。想调:Settings → Variables 里设 `REFRESH_DAYS`(默认 21)和 `REFRESH_LIMIT`(默认 25)。上面「内容太少怎么调」里的 `MIN_ER` 等变量现在会真正传给抓取脚本。

**自动抓取只需要设置一次(之后都在网页上完成):**

1. 打开网页「管理竞对」→ 展开 **自动抓取设置**
2. 按里面的 4 步,到 GitHub 建一个**只限这个仓库、只开 Actions 读写**的令牌(Fine-grained token)
3. 把仓库名(用户名/仓库名)和令牌填进去,点保存。令牌只存进数据库,网页读不回来,也不要发给别人
4. 令牌有有效期(GitHub 建令牌时选的)。过期后通知会失败,面板会提示,重新建一个再保存即可;没设置也没关系,新账号就等每周一抓

**还没设置自动抓取、或通知失败时:** 账号照样会加进去,只是要等周一,或去 Actions → **Sync Content** → Run workflow(把 `only_new` 填 `true` 就只抓新账号)。

**面板里的「现在抓新账号」按钮:** 补设好令牌之后、或上次通知失败时,点一下就会触发一次只抓新账号的同步。已经标记为「抓取失败」的账号不会被反复重抓,先「停止追踪」再「恢复」才会清掉标记再试一次。

**换口令:** 直接在网页上换:「管理竞对」→ 先验证现在的口令 → 展开 **更换团队口令** → 输入新口令(至少 8 个字符)→ 点更换。这台电脑会记住新口令,其他人下次操作时重新输入即可。
**忘记口令了:** 到 Supabase 的 SQL Editor,把 `admin_competitors.sql` 最底下那段 `p text := '...'` 改成新口令,整段重跑一次(只有忘记口令时才需要)。

## 🎬 我的稿:把爆款改写成你的口播稿(不用改代码)

系统每周除了 AI 拆解,还会把每条爆款**按你的人设、语气、受众和红线**改写成一段 30-60 秒、可以直接对着镜头念的中文口播稿,放在卡片上绿色的「🎬 我的版本」里;点 **我的稿** 一键复制,点 **Brief** 也会一起带上。

**第一次一定要做的:告诉 AI 你是谁。**

1. 回到安装页第 6 步,把上一堂课的 `voice-guide.md` 和 `business-context.md` 放进去,下载拼好的 `brand_voice.md`
2. 到**你的仓库**首页 → **Add file** → **Upload files**,把 `brand_voice.md` 拖进去
3. 点绿色 **Commit changes**
4. 让 AI 用新语气**重刷**已经生成的稿子:Actions → 左边 **Rewrite To My Voice** → Run workflow → `rewrite_all` 填 `1` → 绿色 Run workflow。等几分钟,再去 Actions → **Deploy Dashboard** → Run workflow 刷网页

之后每周新抓到的帖子会自动带上你语气的稿子,不用再管。以后想换语气就重复 1-4。

> 💡 仓库里还没有 `brand_voice.md` 之前,AI 会按你 Variables 里的 `NICHE` 套一个通用人设写——稿子能用,但不像你,所以第一次务必做。
> 💡 用的是第 4 步那把免费的 `GEMINI_API_KEY`;有 Claude key 的加 `ANTHROPIC_API_KEY` 会优先用 Claude,稿子更像人话。
> 💡 `NICHE` 变量决定 AI 拆解的方向,`brand_voice.md` 决定「我的稿」的语气,两个都设了效果最好。

## 📘 同时追踪 Facebook 主页

除了 IG,系统也能抓**公开 Facebook 主页**的帖子,和 IG 放在同一个看板里(顶部「全部 Tracker」下拉可以只看 IG 或只看 FB)。

1. Supabase → SQL Editor,跑 `加竞对.sql` 里 Facebook 那一段(`tracker` 填 `FB`,`username` 填主页名,例如 `facebook.com/deluxmalaysia` 就填 `deluxmalaysia`)
2. Actions → **Sync Content** → Run workflow。它会先抓 IG,再抓 FB;FB 失败不会影响 IG 继续往下跑
3. 不用新增任何钥匙,沿用 `APIFY_TOKEN`

FB 和 IG 的差别:
- 只能追踪**公开主页**,不能追个人账号、群组
- FB 的「赞」是全部表情反应总数;互动率普遍比 IG 低,所以 FB 默认门槛更低(互动率 0.5%、评论 5 条)
- 分享数和播放数目前不入库,不影响分数
- FB 视频没有自动转录(口播栏会是空的),AI 拆解和「我的稿」只依据帖子文案
- Apify 官方 Facebook 抓取按条计费(官方页面写约 US$5/1000 条,加日期筛选另加),建议先只加 2-3 个主页看用量

## 卡住了

| 现象 | 怎么办 |
|---|---|
| 网页 404 | 先等首跑完整结束;再看 Actions 里有没有红色失败的 workflow |
| 卡片上没有「我的稿」按钮(但有 AI 拆解) | ① 这条帖子没有口播稿也没有像样的文案,AI 没材料改;② 首跑还没跑到这一步,等下周或去 Actions → **Rewrite To My Voice** 手动跑;③ 老学员用旧 `schema.sql` 建的表没有 `my_script` 这一列——看 Actions 里 Analyze Posts 的日志,它会告诉你要贴的那一句 SQL |
| 抓到 0 条 | 打开 Actions → Sync Content 的日志,看那张**逐个账号的表格**:`抓到` 是 0 = 账号名拼错或 active 没勾;`抓到` 有数但 `入选` 是 0 = 门槛太严,照下面「内容太少怎么调」加 Variables |
| 内容太少 | 见下面「内容太少怎么调」 |
| AI 拆解空 / 没有「我的稿」 | ① Secrets 里没加 `GEMINI_API_KEY`(名字要一模一样);② Gemini 免费额度当天用完,隔天自动补;③ 看 Actions → **Analyze Posts** 的日志:第一行 `[Provider]` 是不是 gemini,每条后面 `FAILED: HTTP` 几 |
| 网页标题还是「爆款雷达」 | Variables 里的 `BRAND` 没设或拼错,设好后 Actions 里重跑 Deploy Dashboard |

## 内容太少怎么调(不用改代码)

系统**已经**把每个竞对最近 60 天的 50 条帖子全抓下来了——Apify 的钱早就花了,只是大部分在入库前被筛掉。所以**放宽门槛完全不额外花钱**。

判定规则(满足**任意一条**就入库,不是全部满足):

1. 互动率 `(赞+评)/粉丝` ≥ `MIN_ER`
2. 评论数 ≥ `MIN_COMMENTS`
3. 互动数 ≥ `OUTLIER_X` × **该账号自己的中位互动**(所以 1000 粉的小号跟自己比,不跟 50 万粉的比)

另外每个账号**保底** `TOP_N_PER_COMP` 条、**封顶** `MAX_PER_COMP` 条,避免一个大号刷屏。

想要更多内容,到**你的仓库** → Settings → Secrets and variables → Actions → **Variables** 分页,New repository variable,加你要改的那几个:

| Variable | 默认 | 想要更多内容就改成 | 作用 |
|---|---|---|---|
| `MIN_ER` | `0.02` | `0.01` | 互动率门槛,2% → 1% |
| `MIN_COMMENTS` | `15` | `8` | 评论数门槛 |
| `MIN_ENGAGE` | `20` | `10` | 噪音底线(赞+评太少的直接丢) |
| `OUTLIER_X` | `1.5` | `1.2` | 超出自家中位数多少倍算爆 |
| `TOP_N_PER_COMP` | `3` | `5` | 每个账号保底几条 |
| `MAX_PER_COMP` | `15` | `25` | 每个账号最多几条 |
| `DAYS_BACK` | `60` | `90` | 回看多少天(**不额外花钱**) |
| `RESULTS_LIMIT` | `50` | `80` | 每个账号抓多少条(⚠️ **这个会加钱**) |

改完到 Actions → Sync Content → Run workflow 重跑即可。

> 💡 最省钱的三个旋钮是 `MIN_ER`、`MIN_COMMENTS`、`DAYS_BACK`——它们只决定「已经抓到的东西留不留」,不决定「抓多少」。只有 `RESULTS_LIMIT` 会真的加 Apify 账单。

> 💡 还是太少?那就是**竞对不够**。到 Supabase → Table Editor → `competitors` 表多加几行。系统每周会自动推荐相关账号(active 未勾),勾上就开始追踪。8–15 个竞对是比较舒服的量。

---

## 三条红线

1. **secret key**(`sb_secret_` 开头)只进 Secrets,不要贴到别处或发群里
2. 仓库是 Public——竞对数据和 AI 拆解任何人拿到链接都能看到,介意就别用免费版
3. `schema.sql` 里的安全锁那段不要删
