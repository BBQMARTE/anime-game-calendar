# 缺图补图任务指令（WorkBuddy 专用）

## 任务定义

`data/manual.json` 中有 52 条活动条目缺图（image 字段为空）。你的唯一任务：为它们逐条找到官方配图并回填。本任务是**收尾清扫**，不是"尽力而为"——每一条都必须交账。

## 铁律（违反任意一条 = 本次任务不合格）

1. **B站动态必须用浏览器子代理打开网页查看，禁止用 WebFetch 或裸 API 抓取**。原因：`opus_feed` 接口的翻页参数被官方忽略、永远只返回最新 20 条；`feed/space` 完整动态流触发 -352 风控、动态搜索触发 -1200（均需登录）。**20 条以外的历史动态（如异环×罗森联动，8 月底发布）只有浏览器滚动加载才能看到**，但那里确实有图，不要跳过。
2. **官网公告页同样优先用浏览器子代理**（列表与正文常为 JS 渲染，WebFetch 会返回空内容）。入口表见文末。
3. **52 条逐条交账**，汇报里不许出现"部分完成""其余类似"这类概括，每条单独一行说明结果。
4. **image 字段留空的条目，必须在汇报中给出具体原因**（列表页无此公告 / 详情页无图 / 图被 JS 动态渲染拿不到），不许写"未找到"三个字了事。
5. 只允许修改 `data/manual.json` 的 `image` 字段，禁止改动其他字段、其他文件。

## 配图来源优先级

1. **B站官方动态图**（用浏览器子代理打开动态页获取，最全、最准，见下节）
2. **官网新闻详情页主图/首图**
3. 官网列表页缩略图
4. WebSearch `site:<官网域名> <活动名>` 找到的官网页面图
5. 降级：官方社区（米游社/hoyolab、库街区）公告图

## 浏览器子代理 browser_use（核心工具，必用）

WebFetch 只能取静态 HTML。以下页面**必须用 Task 工具派 `browser_use` 子代理**打开：

| 场景 | 为什么 WebFetch 不行 |
|---|---|
| B站官号动态页 | SPA 渲染；历史动态需滚动加载（API 只给最新 20 条） |
| B站搜索页 | SPA，WebFetch 只能拿到页脚 |
| 米哈游/库洛等官网新闻 | 列表与正文为 JS 动态渲染 |
| 带 Referer 防盗链的图床 | 需浏览器上下文才能取到图 |

**派发句式**（照此写，不要只写"用浏览器打开"）：

> 用 Task 工具派 browser_use 子代理执行：打开 `<URL>`，向下滚动加载（每次约 10 条），查找含「<关键词>」的动态，找到后截图并转写该动态的完整正文、发布时间与全部配图直链；未找到则继续滚动直到页尾，并如实回报「已滚动 N 屏未找到」。

### 流程 A：找 B站历史动态的图

1. 用 Task 工具派 browser_use 子代理打开 `https://space.bilibili.com/<UID>/dynamic`（UID 见下表）
2. 在页面内查找目标关键词（如"罗森"）；未找到则**向下滚动加载更多**（每次约 10 条），重复查找
3. 找到后点击该动态进入 `https://www.bilibili.com/opus/<id>` 详情页
4. 点击图片放大，从浏览器地址栏读取图片直链（形如 `https://i0.hdslb.com/bfs/new_dyn/xxx.jpg`）
5. 该直链可直接填 image 字段（hdslb.com 在服务端白名单，前端自动走 `/api/img` 代理）
6. 若动态是**一张长图内含多个活动卡片**，按「长图切割」流程处理：多模态定位边界 → PIL 裁剪 → 存 `static/img/<game_id>/` → 逐张回填

### 流程 B：找官网公告的图

1. 用 Task 工具派 browser_use 子代理打开官网新闻列表页
2. 滚动加载，定位目标公告标题
3. 点击进入详情页，读取正文首图地址
4. 拿不准图片内容是否对应时，用多模态看图确认后再回填

### B站官号 UID

| 游戏 | UID |
|---|---|
| 崩坏：星穹铁道 | 1340190821 |
| 绝区零 | 1636034895 |
| 明日方舟：终末地 | 1265652806 |
| 明日方舟 | 161775300 |
| 鸣潮 | 1955897084 |
| 异环 | 3546636978489848 |
| 重返未来：1999 | 1197454103 |

### 汇报要求

凡用到浏览器子代理的条目，注明「经浏览器子代理打开 &lt;URL&gt; 获取」。

## image 字段填法

| 图的来源域名 | 填法 |
|---|---|
| mihoyo.com / hoyoverse.com / hoyolab.com / hypergryph.com / kurogame.com / kurobbs.com / wanmei.com / taptap.cn / akamaized.net 等（服务端白名单） | 直接填完整 URL，前端自动走 `/api/img` 代理 |
| sl916.com（1999 官方图床） | **必须填 `http://` 开头**（https 会 502），如 `http://res.sl916.com/...` |
| 其他白名单外域名 | 下载图片存 `static/img/<game_id>/<拼音名>.jpg`，image 填 `/static/img/<game_id>/<拼音名>.jpg` |

下载落盘用 python（requests 需 `trust_env=False` 绕系统代理）：

```python
import requests, shutil
from pathlib import Path
s = requests.Session(); s.trust_env = False
s.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': '<来源页>'})
r = s.get('<图URL>', timeout=20)
Path(r'static/img/<game_id>').mkdir(parents=True, exist_ok=True)
open(r'static/img/<game_id>/<拼音名>.jpg', 'wb').write(r.content)
```

## 回填方法（禁止手工编辑 JSON 出错）

写 python 脚本按 `game_id + title` 精确匹配回填，先备份：

```python
import json, shutil
shutil.copy('data/manual.json', 'data/manual.json.bak')
data = json.load(open('data/manual.json', encoding='utf-8'))
fills = {  # (game_id, 精确标题) : 图URL或本地路径 —— 你逐条填入
    ('hsr', '混沌回忆·扫除风暴'): '<图URL>',
}
n = 0
for e in data:
    if isinstance(e, dict) and not e.get('image'):
        key = (e.get('game_id'), e.get('title'))
        if key in fills:
            e['image'] = fills[key]; n += 1
json.dump(data, open('data/manual.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('回填', n, '条')
```

回填后验证：`curl -X POST http://127.0.0.1:5000/api/refresh -H "X-Requested-With: ycal"`，等 30 秒后 `curl http://127.0.0.1:5000/api/events` 确认新 image 对外可见。若服务未运行则跳过此步，在汇报中注明。

## 官网新闻入口

| 游戏 | game_id | 入口 |
|---|---|---|
| 崩坏：星穹铁道 | hsr | https://sr.mihoyo.com/news/ （抓不到时 WebSearch `site:sr.mihoyo.com <活动名>`） |
| 绝区零 | zzz | https://zzz.mihoyo.com/news/ （或 WebSearch `site:zzz.mihoyo.com <活动名>`） |
| 明日方舟：终末地 | endfield | https://endfield.hypergryph.com/news |
| 鸣潮 | wuwa | https://mc.kurogame.com （详情页形如 /main/news/detail/<id>） |
| 异环 | ananta | https://yh.wanmei.com/news （栏目页形如 /news/<cat>/index.html） |
| 重返未来：1999 | r1999 | https://re.bluepoch.com （详情页形如 /home/detail.html#newsId?<id>） |

官网为 JS 动态渲染导致 WebFetch 拿不到内容时：改用 WebSearch `site:<域名> <关键词>` 定位详情页；仍不行则记录"列表/详情被动态渲染，无法解析"。

## 缺图清单（52 条，标题一字不差用于精确匹配）

### r1999（15 条）
1. 4.0版本「应门者」特别前瞻节目（直播）
2. 【迁流的盛宴】重映活动
3. 【不渝者的领航】巡游限定征集（4.0上半）
4. 【应门者·签到活动】登录送二十连
5. 4.0活动正篇「应门者」（主线第十四章）
6. 【圆桌功勋册】
7. 【国王银禧宴会】兑换商店
8. 【迭奏之夜】庆典活动
9. 【红隼奏鸣】登录送十连
10. 【海岸的捡拾】登录赠迷思之茧·37与全新心相
11. 【隙中仙境】剧情拓展系统
12. 【天真的预言】贝丽尔轶事
13. 【光影栖息处】
14. 【众声的谱成】
15. 【德雷克·未誓者】角色剧情活动

### ananta（13 条）
1. 逐光破浪
2. 环期赏令
3. 轨外回响
4. 「名月特刊」弧盘研募·行进于时间之外（返场）
5. 炭团的宝藏
6. 咔滋！黄金双脆
7. 噗卡翻翻乐
8. 活力焕能
9. 像素溢出
10. 夺金大作战
11. 轨外之境「夕照环线」
12. 环期赠礼（1.4版本七日签到）
13. 异环×罗森 联动开启

### wuwa（7 条）
1. 烟云赠礼
2. 群声共振模拟域
3. 清弦纪流年
4. 全息战略·万囮牢·朽躯
5. 「千般渡」武器活动唤取
6. 「灼霜」武器活动唤取（下半）
7. 「宙算仪轨」武器活动唤取（下半）

### zzz（7 条）
1. 丽都城募
2. 「惊喜放映企划」签到（14天，自选妄想天使时装）
3. 先遣赏金-区域巡防（双倍奖励）
4. 锵锵！球仔成长日记
5. 「嗯呢」从天降（累计登录送邦布券）
6. 跛脚乌鸦奇探录
7. 数据悬赏-实战模拟（双倍奖励）

### hsr（6 条）
1. 命运契约·再启（免费领联动五星）
2. 远坂凛/吉尔伽美什 联动跃迁（常驻至4.6版本）
3. 混沌回忆·扫除风暴
4. 末日幻影·仙客天狼
5. 虚构叙事·立界开篇
6. 异相仲裁·军团再临（4.5版本）

### endfield（4 条）
1. 军列申领（1.5上半专武池）
2. 明曜申领（1.5上半专武池）
3. 新区域「武陵-雪松林」开放
4. 新区域「武陵-遂明」开放

## 提示

- 版本更新公告往往包含多个子活动的宣传图（如 1999 的【圆桌功勋册】【国王银禧宴会】可能同属 4.0 版本公告），可以从同一篇版本公告的不同段落图分别取用。
- 深渊/肉鸽周期玩法（混沌回忆、末日幻影、虚构叙事、群声共振模拟域等）若无独立公告，可用其玩法图或对应版本公告内插图。
- 卡池/武器唤取公告标题在官网上通常是「角色活动唤取」「武器活动唤取」类，按角色名/武器名搜索。
- 多图公告取**最能代表该活动的第一张**；拿不准就取信息量最大的主视觉图。

## 汇报格式（最后输出）

```
补图结果: X/52
[游戏] 条目标题 → 已填 <URL或路径>（来源: 官网详情页/WebSearch/落盘）
[游戏] 条目标题 → 未填（原因: <具体>，已尝试: <列表页/详情页/WebSearch>）
```

52 行，一行不多一行不少。
