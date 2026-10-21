# syc sync

把 **西安交通大学思源学堂（lms.xjtu.edu.cn）首页「待办」** 里的作业、测验、截止时间和作业说明，自动写入 **《Chill With You : Lo-Fi Story》**：

- **笔记页面**：完整内容，一行一条作业，格式为
  `《课程名》作业名称：作业说明，截止时间：2026-10-18 23:59`
- **待办列表**：只放短标题（避免小输入框把长文本截断），保留截止日期，方便当索引。

- 数据来源：`https://lms.xjtu.edu.cn/api/todos`（首页「待办」卡片的数据）
- 作业说明：逐条读取 `/api/activities/{id}`，测验读取 `/api/exams/{id}`
- 笔记写入：`NoteList` + `PageDataV2`（页面标题「LMS 作业」）
- 不改游戏本体，不注入进程；只在游戏关闭时改写存档，写前自动备份

> 本项目不附带任何账号、Cookie、课程数据或存档；所有 LMS 数据都由使用者本机登录后获取。

---

## 一、笔记页面格式

游戏「笔记」中会新建一页 **LMS 作业**，内容每个作业一行：

```
《示例课程》示例作业：这里是作业说明，截止时间：2026-10-18 23:59
《另一门课程》章节练习：LMS 尚未解锁，截止时间：2026-10-25 23:59
```

说明：

- `《课程名》` 里的课程名会去掉「（2026-2027学年第一学期）」这类学期后缀，避免多余括号；
- 模板里的 `（课程名）（作业名称）（作业说明）（截止时间）` 占位括号已全部替换，不会出现在结果里；
- **作业说明本身**里的括号（例如数学题的 `1（2）`）会原样保留，否则会破坏题目内容；
- 没有说明的作业/测验写「无说明」，未解锁的写「LMS 尚未解锁」；
- 截止时间格式为 `年-月-日 时:分`（中国标准时间）；
- 完整内容也保存在 `data/lms_todos.json` 和 `data/lms_todos.txt`，可随时查看。

---

## 二、第一次使用

1. 先**关闭游戏**（游戏运行时不能改存档，会被内存数据覆盖）。
2. 双击 **`Sync Now.bat`**。
3. 如果弹出 Edge 登录页，请完成西交统一身份认证登录（账号密码 / 手机动态码 / 扫码均可）。
   - 登录信息只保存在本目录 `browser-profile`，不会上传到任何第三方。
   - 登录成功后脚本自动继续，窗口自动关闭。
4. 看到 `已写入待办…`、`笔记：新增 … 行` 即成功。打开游戏 → 笔记 → 「LMS 作业」即可查看。

以后会话仍有效时，直接双击 `Sync Now.bat` 即可。

---

## 三、自动同步

双击 **`Install Auto Sync.bat`**：

- 在 Windows「启动」文件夹创建快捷方式，登录 Windows 后后台运行 `watch.py`；
- 默认每 120 分钟用**无头 Edge** 刷新一次 LMS；
- **检测到游戏退出后，立即把缓存写入存档**，下次启动游戏就是最新的；
- 全程无控制台窗口、无弹窗。

取消：双击 **`Uninstall Auto Sync.bat`**。

### 弹出窗口问题

之前后台每 20 秒调用一次 `tasklist` 检查游戏进程，没有隐藏控制台，导致频繁闪窗。现在：

- 所有 `tasklist` / WebDriver 子进程都使用 `CREATE_NO_WINDOW` + 隐藏窗口启动；
- Edge 自动同步使用 `--headless=new`，不显示浏览器窗口；
- 检查间隔改为 30 秒。

如果仍然觉得有窗口/资源占用，可把 `config.json` 的 `"auto_mode"` 改成 `"on_exit"`：

- 只在**游戏退出时**应用缓存 + 刷新一次 LMS；
- 不再定时后台访问 LMS；
- 效果就是“下次打开游戏时”待办和笔记已经是最新的。

修改 `auto_mode` 或 `fetch_interval_minutes` 后，重新双击一次 `Install Auto Sync.bat`，让后台进程重新读取配置。

---

## 四、删除规则（笔记）

- Mod 写入笔记后，会记住每一行对应哪条 LMS 作业。
- 如果你在笔记里**删除某一行**（或改写这一行），下次同步会认为这条作业被删除，**即使 LMS 待办里仍有它，也不会再写回**。
- 如果你把整个「LMS 作业」页面删掉，之前写过的所有作业都会被标记为“不再写入”；之后新出现的作业会在新页面里重新建立。
- 想恢复某条被屏蔽的作业：关闭游戏，编辑 `data/note_state.json`，从 `suppressed` 数组里删掉对应的 key，再运行一次同步。
- 待办列表中的任务仍然按 LMS 待办刷新（已完成的会保留完成状态）。笔记的删除不会影响待办列表。

---

## 五、配置文件 `config.json`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `target_list_title` | `待办事项列表` | 写入哪个游戏待办列表 |
| `fallback_to_first_list` | `true` | 找不到上面标题时，改用第一个待办列表（适配英文/改名） |
| `include_types` | `["homework","exam"]` | 同步类型 |
| `include_description` | `true` | 是否抓取作业说明 |
| `note_enabled` | `true` | 是否写入笔记页面 |
| `note_title` | `LMS 作业` | 笔记页面标题 |
| `note_page_first` | `true` | 把「LMS 作业」放在笔记列表第一位，打开笔记时优先选中 |
| `remove_empty_default_pages` | `true` | 删除游戏自动生成且内容为空的「新页面」，避免打开笔记只看到空白页 |
| `note_description_max_chars` | `2000` | 笔记里说明的最大字数（0 = 不限制） |
| `description_max_chars` | `200` | 旧版待办文本长度，现仅保留兼容 |
| `title_prefix` | `""` | 旧版待办前缀，现仅保留兼容 |
| `include_locked` | `true` | 是否包含 LMS 尚未解锁的任务 |
| `remove_stale` | `true` | LMS 中消失的未完成待办是否从游戏待办删除 |
| `headless_auto` | `true` | 自动模式是否使用无头 Edge |
| `fetch_interval_minutes` | `120` | 后台刷新间隔（分钟，最小 30） |
| `auto_mode` | `periodic` | `periodic` 定时刷新；`on_exit` 只在游戏退出时刷新 |
| `edge_binary` / `driver_path` | `""` | 一般不用填 |
| `profile_dir` | `browser-profile` | 保存 LMS 登录 Cookie |
| `game_process` | `Chill With You.exe` | 游戏进程名 |

---

## 六、数据与备份

| 路径 | 内容 |
|---|---|
| `data/lms_todos.json` | 最近一次抓取的完整数据（含完整说明、LMS 链接） |
| `data/lms_todos.txt` | 人类可读的待办清单 |
| `data/state.json` | 待办任务的稳定 ID / 管理状态 |
| `data/note_state.json` | 笔记页面 ID、已写入行、已屏蔽作业 |
| `logs/sync-*.log` | 同步日志 |
| `logs/watcher.log` | 后台自动同步日志 |
| `backups/` | 改写前的 `.es3` 备份（待办、NoteList、PageDataV2，保留最近 50 份） |

存档位置：

```
%USERPROFILE%\AppData\LocalLow\nestopi\Chill With You\SaveData\Release\v2\<SteamID>\
```

---

## 七、常见问题

**Q：打开笔记看到的是空白页？**  
游戏会默认新建并选中一个空的「新页面」，容易让人以为笔记没写入。新版会把这个空白页复用/重命名为「LMS 作业」，并删除多余的空「新页面」，打开笔记就是内容页。如果旧版已经留下了空白页，关闭游戏后重新运行一次 `Sync Now.bat` 即可清理；也可以手动点一下列表里的「LMS 作业」。

**Q：笔记里某条作业删掉后又出现了？**  
正常不会。只有 `data/note_state.json` 被删除/重建，或这一行被改写导致匹配不上时，才可能重新出现。检查 `suppressed` 列表。

**Q：笔记页面被我不小心删了，怎么恢复全部作业？**  
关闭游戏，删除 `data/note_state.json`，再运行 `Sync Now.bat`。会新建「LMS 作业」页并写入当前所有待办（之前删除页面的屏蔽记录也会清空）。

**Q：待办里只显示短短几个字？**  
这是故意的。游戏待办输入框很小，长文本会被截断甚至写坏；完整内容在「LMS 作业」笔记页。

**Q：自动同步还会弹窗吗？**  
正常情况下不会。若仍有，设置 `"auto_mode": "on_exit"`，并把 `fetch_interval_minutes` 调大。

**Q：LMS 登录失效？**  
手动双击 `Sync Now.bat` 重新登录。

**Q：游戏正在运行？**  
关闭游戏后再同步；装有自动同步时，退出游戏后几秒内会自动写入。

**Q：会保存我的 LMS 密码吗？**  
不会。脚本不读取、不保存密码，只复用 Edge 配置目录里的登录 Cookie。

---

## 八、目录结构

```
syc-sync/
├─ Sync Now.bat                 手动同步（首次登录也用它）
├─ Install Auto Sync.bat        安装开机自启 + 后台同步
├─ Uninstall Auto Sync.bat      卸载自动同步
├─ config.json                  配置
├─ sync.py                      同步主程序
├─ watch.py                     后台监视器
├─ lms_client.py                Edge WebDriver + LMS API
├─ game_save.py                 存档/笔记读写与合并
├─ tasks.py                     LMS 数据 → 待办/笔记文本
├─ es3json.py                   ES3 JSON 解析/生成
├─ driver_setup.py              msedgedriver 版本匹配
├─ runtime/                     内置 Python 3.12
├─ tools/msedgedriver.exe       Edge WebDriver
├─ browser-profile/             LMS 登录 Cookie（运行时生成）
├─ data/                        缓存/状态（运行时生成）
├─ logs/                        日志（运行时生成）
└─ backups/                     存档备份（运行时生成）
```

---

## 九、实现原理（简述）

1. `msedgedriver` 启动独立 Edge 配置目录，复用已登录的 LMS 会话；
2. 在页面上下文 `fetch('/api/todos')`，再并发请求每条作业/测验详情；
3. 作业说明 HTML 转纯文本；笔记行按 `《课程名》作业名：说明，截止时间：…` 生成；
4. 用稳定哈希 ID 合并待办；用「页面 ID + 已写行文本」管理笔记：
   - 已写行还在 → 不重复写；
   - 已写行被删除/改写 → 加入 `suppressed`，以后不再写；
   - 整个页面被删除 → 所有旧行加入 `suppressed`，新作业另建页面；
5. 以 gzip + ES3 JSON 写回 `TodoListData`、`NoteList`、`PageDataV2`，写前备份。

所有请求只访问 `lms.xjtu.edu.cn`（以及必要时 `msedgedriver.microsoft.com` 下载驱动），没有第三方服务器。
