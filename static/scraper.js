/* 二游活动日历 - 端内抓取器(Android WebView 模式使用)
   与 Python 版 scrapers.py 逻辑一致,仅访问官方公开接口 */
const Scraper = (() => {
  const GAMES = [
    { id: 'hsr',       name: '崩坏：星穹铁道', color: '#b688ff' },
    { id: 'zzz',       name: '绝区零',         color: '#ff7a45' },
    { id: 'endfield',  name: '明日方舟：终末地', color: '#ff5f8f' },
    { id: 'wuwa',      name: '鸣潮',           color: '#35d0ba' },
    { id: 'ananta',    name: '异环',           color: '#f254c7' },
  ];

  async function httpText(url) {
    const r = await fetch(url, { headers: { 'Accept': '*/*' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.text();
  }
  async function httpJson(url) { return JSON.parse(await httpText(url)); }

  /* ---------- 时间解析(timeparse.py 移植 · 增强版) ---------- */
  // 全角数字/标点 → 半角,统一正则
  function normText(s) {
    if (!s) return '';
    const map = { '０': '0', '１': '1', '２': '2', '３': '3', '４': '4', '５': '5', '６': '6', '７': '7', '８': '8', '９': '9', '：': ':', '．': '.', '～': '~', '—': '-', '－': '-' };
    return s.replace(/[０-９：．～—－]/g, c => map[c] || c);
  }
  // 带年份:2026年7月10日 / 2026/07/10 / 2026.07.10 / 2026-07-10
  const DATE_Y = /(?<y>\d{4})\s*(?:年|[\/.\\-])\s*(?<m>\d{1,2})\s*(?:月|[\/.\\-])\s*(?<d>\d{1,2})\s*日?/g;
  // 不带年份:7月10日 / 7/10 / 07.10(不用 -,避免拆 YYYY-MM-DD)
  const DATE_MD = /(?<![\d\/.\-])(?<m>\d{1,2})\s*(?:月|[\/.])\s*(?<d>\d{1,2})\s*日?/g;
  // 时间:12:00 / 12:00:00 / 12点(30分) / 12时(30分)
  // /y(sticky):必须锚定在日期紧跟的位置,与 Python _TIME.match(text,pos) 一致
  // (若用 /g 会从 pos 向后搜索,把远处的"12:00"偷给当前日期,污染 token.end/hasTime)
  const TIME_RE = /\s*(?:(?<h1>\d{1,2})\s*[:：]\s*(?<mi1>\d{1,2})(?:\s*[:：]\s*(?<s1>\d{1,2}))?|(?<h2>\d{1,2})\s*点\s*(?<mi2>\d{1,2})?\s*分?|(?<h3>\d{1,2})\s*时\s*(?<mi3>\d{1,2})?\s*分?)/y;
  const LONG_RE = /(?:长期|常驻|永久|持续开放|常开|长期开放|不限时|无期限)\s*(?:开放|开启|活动|进行|存在)?/;
  const KW_RE = /(活动时间|活动期间|活动开放时间|开放时间|开启时间|上线时间|开始时间|祈愿时间|跃迁时间|寻访时间|招募时间|唤取时间|卡池时间|上架时间|售卖时间|维护时间|更新时间|兑换时间|领取时间|投稿时间|征集时间|挑战时间|接力时间|直播时间|前瞻时间|演出时间|预约时间|开放预约时间|报名|截止|结束时间)[:：]?\s*/g;
  const VER_AFTER = /(版本更新后|更新完成后|维护后|开服后|开启后|更新后|维护结束)/;
  const RANGE_SEP = /(?:~|～|—|–|至|到|\s[-\u2010\u2011]\s)/;

  function htmlToText(html) {
    if (!html) return '';
    return html.replace(/<[^>]+>/g, ' ').replace(/&\w+;/g, ' ').replace(/\s+/g, ' ');
  }
  function mkDate(y, mo, d, h, mi, ref) {
    const Y = y ? +y : ref.getFullYear();
    mo = +mo; d = +d;
    const hh = (h != null && h !== '') ? +h : 0;
    const mm = (mi != null && mi !== '') ? +mi : 0;
    // 时分越界丢弃整个 token(与 Python datetime 抛 ValueError 一致;
    // new Date 会自动进位,如 25:00 变次日 1 点,导致双端解析分叉)
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || hh > 23 || mm > 59) return null;
    const dt = new Date(Y, mo - 1, d, hh, mm, 0);
    return isNaN(dt) ? null : dt;
  }
  function parseTime(s, pos) {
    TIME_RE.lastIndex = pos;
    const m = TIME_RE.exec(s);
    if (!m) return [0, 0, pos, false];
    const g = m.groups;
    let h, mi;
    if (g.h1 != null) { h = +g.h1; mi = g.mi1 != null ? +g.mi1 : 0; }
    else if (g.h2 != null) { h = +g.h2; mi = g.mi2 != null ? +g.mi2 : 0; }
    else { h = +g.h3; mi = g.mi3 != null ? +g.mi3 : 0; }
    return [h, mi, m.index + m[0].length, true];
  }
  // 返回按出现顺序去重后的日期 token:[{dt,start,end,hasTime}]
  function findDateTokens(text, ref) {
    const norm = normText(text);
    const toks = [];
    for (const [rx, hasYear] of [[DATE_Y, true], [DATE_MD, false]]) {
      rx.lastIndex = 0; let m;
      while ((m = rx.exec(norm))) {
        const after = norm.slice(m.index + m[0].length, m.index + m[0].length + 4);
        if (after.startsWith('版本')) continue;                       // 跳过版本号 4.4版本
        const vb = norm.slice(m.index, m.index + 8);
        if (/^\s*(?:v|V)?\d+[.\/]\d+\s*版本/.test(vb)) continue;       // V4.4版本
        const y = hasYear ? m.groups.y : null;
        const [h, mi, endpos, hasTime] = parseTime(norm, m.index + m[0].length);
        const dt = mkDate(y, m.groups.m, m.groups.d, h, mi, ref);
        if (dt) toks.push({ dt, start: m.index, end: endpos, hasTime });
      }
    }
    toks.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
    const dedup = [];
    for (const t of toks) {
      if (dedup.some(k => t.start >= k.start && t.end <= k.end)) continue;
      dedup.push(t);
    }
    return dedup;
  }
  function applyTok(tok, isEnd) {
    const dt = new Date(tok.dt.getTime());
    if (isEnd && !tok.hasTime) dt.setHours(23, 59, 59, 0);
    return dt;
  }
  function fixOrder(s, e) {
    if (e < s) e = new Date(e.getFullYear() + 1, e.getMonth(), e.getDate(), e.getHours(), e.getMinutes(), e.getSeconds());
    return [s, e];
  }
  // 判断区间分隔符在 token 的前面还是后面;返回 'before','after','both',null
  function rangeSepSide(text, start, end) {
    const b = text.slice(Math.max(0, start - 15), start).replace(/\s+$/,'');
    const sepB = RANGE_SEP.test(b.slice(-4));                      // 最后 4 个字符是否有分隔符
    const a = text.slice(end, Math.min(text.length, end + 20)).replace(/^\s+/,'');
    const sepA = RANGE_SEP.test(a.slice(0, 4));                    // 最前面 4 个字符是否有分隔符
    if (sepB && sepA) return 'both';
    if (sepB) return 'before';
    if (sepA) return 'after';
    // 放宽:检查整个附近区域
    const near = text.slice(Math.max(0, start - 20), end + 20);
    return RANGE_SEP.test(near) ? 'near' : null;
  }
  function rangeInSeg(seg, ref) {
    const toks = findDateTokens(seg, ref);
    if (toks.length >= 2) return fixOrder(applyTok(toks[0], false), applyTok(toks[1], true));
    if (toks.length === 1) return [applyTok(toks[0], false), null];
    return [null, null];
  }
  function extractRange(text, refDate) {
    if (!text) return [null, null];
    const ref = refDate || new Date();
    const norm = normText(text);
    if (LONG_RE.test(norm)) return [ref, null];                       // 长期/常驻:无结束
    const toks = findDateTokens(norm, ref);
    // 1) 关键词优先:在其后 200 字符内取日期
    KW_RE.lastIndex = 0; let kw;
    while ((kw = KW_RE.exec(norm))) {
      const lo = kw.index + kw[0].length, hi = lo + 200;
      const ctx = norm.slice(Math.max(0, kw.index - 60), hi);         // 含「版本更新后」前后文
      const segToks = toks.filter(t => t.start >= lo && t.start < hi);
      if (segToks.length >= 2) { const [s, e] = fixOrder(applyTok(segToks[0], false), applyTok(segToks[1], true)); return [s, e]; }
      if (segToks.length === 1) {
        const t = segToks[0];
        if (VER_AFTER.test(ctx)) return [ref, applyTok(t, true)];           // 版本更新后~date → [ref, end]
        const side = rangeSepSide(norm, t.start, t.end);
        if (side === 'before' || side === 'both') return [ref, applyTok(t, true)];  // ~date → end
        if (side === 'after') return [applyTok(t, false), null];            // date~ → start
        if (side === 'near') return [ref, applyTok(t, true)];               // 附近有分隔符，保守当结束
        return [applyTok(t, false), null];                                  // 无分隔符，单日期 = 开始
      }
    }
    // 2) 无关键词兜底:需同时满足①两个日期紧挨 ②它们之间有区间分隔符
    for (let i = 0; i < toks.length - 1; i++) {
      const gap = toks[i + 1].start - toks[i].end;
      if (gap <= 60) {
        const between = norm.slice(toks[i].end, toks[i + 1].start);
        if (RANGE_SEP.test(between)) {
          const [s, e] = fixOrder(applyTok(toks[i], false), applyTok(toks[i + 1], true));
          return [s, e];
        }
      }
    }
    if (toks.length === 1) {
      // 「版本更新后」等也在兜底路径检查
      if (VER_AFTER.test(norm)) return [ref, applyTok(toks[0], true)];
      return [applyTok(toks[0], false), null];
    }
    return [null, null];
  }

  /* ---------- 工具 ---------- */
  function classify(title, dft) {
    const t = title || '';
    if (/祈愿|跃迁|卡池|寻访|招募|唤取|调频|UP|概率|光锥|音擎|补给|限定|联动角色|星琼|请托|征募/i.test(t)) return '角色与专武';
    // 收紧:去掉"开放|开启|玩法"(几乎所有公告都命中),"节|杯|赛"移到更精确上下文
    if (/活动|挑战|签到|福利|征集|赛事|联动|前瞻|直播|试炼|竞猜|累充|兑换|限时|双倍|巡演|盛典|嘉年华/i.test(t)) return '活动';
    if (/维护|更新|修复|公告|说明|公示|封禁|补偿|停服|版本更新说明/i.test(t)) return '公告';
    // 宽松兜底:如果有「活动名」再加日期+开启/开放,才算活动;否则资讯
    if (/「[^」]+」.*(?:开启|开放|上线|正式)/.test(t)) return '活动';
    return dft || '资讯';
  }
  /* 日历用短标题:活动取第一个「」名,卡池取第二个「」内的角色/武器名 */
  const BAD_SHORT = new Set(['活动', '菲林', '奖励', '登录', '签到', '福利', '母带']);
  function shortTitle(title, cat) {
    const parts = [...(title || '').matchAll(/「([^」]{2,24})」/g)].map(m => m[1]);
    if (!parts.length) return (title || '').slice(0, 24);
    const name = ((cat === '角色与专武' && parts.length >= 2) ? parts[1] : parts[0]).replace(/[(（].*?[)）]/g, '').trim();
    if (!name || BAD_SHORT.has(name)) return (title || '').slice(0, 24);
    return name.slice(0, 18);
  }
  const iso = d => d ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:00` : null;
  let _uid = 0;
  function ev(gid, gname, title, category, pub, start, end, link, img, kind, ext) {
    title = (title || '').replace(/\s+/g, ' ').trim();
    if ((kind || 'event') === 'event') {
      title = shortTitle(title, category);  // 月历条目用短标题
      // 补 2 天默认窗口:有 start 按 start 补;无 start 用 pub(发布日期)兜底
      const s = start || pub;
      if (s) {
        const ps = s.getTime();
        const pe = end ? end.getTime() : 0;
        if (!end || pe < ps) end = new Date(ps + 2 * 864e5);
        if (!start) start = s;  // pub 兜底时也填 start
      }
    }
    const o = {
      id: `${gid}-${(_uid++).toString(36)}${(title.length * 7 % 997)}`,
      game_id: gid, game: gname,
      title,
      category,
      start: iso(start), end: iso(end), date: iso(pub),
      link: link || '', image: img || '',
      kind: kind || 'event',  // event=真活动/卡池(上月历)  info=公告/资讯
    };
    // 米哈游事件:附带 ann_id 以便点击时用内容 API 打开详情
    if (ext && ext.ann_id) { o.ann_id = ext.ann_id; o._content_api = ext.api; o._content_params = ext.params; }
    return o;
  }

  /* ---------- 分级过滤词表(与 scrapers.py 一致) ---------- */
  const NOISE_RE = /更新说明|更新修复|修复与优化|玩法说明|赛季说明|全新内容一览|内容一览|途径一览|获取途径|维护|停服|补偿|防沉迷|用户协议|隐私|封号|封禁|优惠券|企业微信|小程序|问题说明|已知问题|异常说明|登录问题|充值|退款|客服|安全公告|问卷|系统优化|功能预告|反馈入口|意见反馈|分享活动|邀请好友|前往参与|查看详情|玩法介绍|合作者档案|工作台|新艾利都|创作者激励|服务器时间|危行任务|潮汐任务|全新活动以及玩法|紧急事件|【版本活动】/;
  const SHOP_RE = /周边|商城|折扣|上新|贩售|限时出售|礼包|优惠券/;
  const POOL_RE = /扭蛋|卡池|祈愿|跃迁|调频|补给|概率\s*UP/i;
  const WEB_RE = /米游社|网页活动|H5/;
  // 标题活动特征(星铁/绝区零的活动常混在"公告"组,靠标题识别)
  const ACT_TITLE_RE = /活动[:：]|活动开启|活动现已|活动进行中|限时双倍|双倍掉落|登录领取|签到/;
  // 绝区零服务端常把地点/角色/系统介绍标为"活动",以下名词单独过滤
  const ZZZ_NON_EVENT = new Set([
    '详见工作台-合作者档案','罗斯凯利法','布亚斯特','齿轮街','影池独舞',
    '今日穿搭','月夜密语','服务器时间','邦布券','梦想家','恶名狩猎','拉力委托',
    '零号空洞','式舆防卫战','危局强袭战','_exclusive_','实战模拟店','电玩店',
    '报刊亭','咖啡店','拉面店','录像店','改装店','玩具店','花店','便利店',
    '治安局','对空六课','奥波勒斯小队','卡吕冬之子','维多利亚家政','狡兔屋','白祇重工','H.S.O.S.6',
    'Random Play','电玩','街机','刮刮卡','报刊','喵吉长官','奖章','纪念币'
  ]);
  // 版本更新说明文(内含完整活动/卡池排期,需拆全文)
  const VER_NOTE_RE = /版本更新说明|版本内容说明|更新说明/;

  /* ---------- 批量活动提取:「活动名」+ 时间范围 ---------- */
  // 多括号活动名(支持 「」『』【】[]（）〈〉 等任意配对)
  const BRACKET_RE = /[「『【\[〈（](?<name>(?:[^」』】\]〉）「『【\[〈（]){2,30}?)[」』】\]〉）]/g;
  // 泛称噪音(不是具体活动)
  const NOISE_NAME = /^(?:版本活动|限时活动|活动|公告|注意|温馨提示?|说明|维护公告?|更新说明|全新版本|版本前瞻|前瞻|直播|特别节目|活动详情|活动一览|版本活动一览|活动预告|新版本|版本更新|版本内容|活动玩法|玩法|登录|签到|福利|奖励|菲林|母带)$/;
  function isNoiseName(n) { return NOISE_NAME.test((n || '').trim()) || BAD_SHORT.has((n || '').trim()); }

  function extractEvents(text, refDate) {
    if (!text) return [];
    const ref = refDate || new Date();
    const norm = normText(text);
    const out = [], seen = new Set();
    // 1) 括号活动名
    BRACKET_RE.lastIndex = 0; let m;
    while ((m = BRACKET_RE.exec(norm))) {
      const name = m.groups.name.trim();
      if (!name || seen.has(name) || isNoiseName(name)) continue;
      const seg = norm.slice(m.index + m[0].length, m.index + m[0].length + 220);
      const [s, e] = rangeInSeg(seg, ref);
      if (s || e) { seen.add(name); out.push([name, s, e]); }
    }
    // 2) 标题行:■/◆/✦ 开头,其后含活动时间
    const HEAD_RE = /[■◆✦★]\s*([^\n■◆✦★]{2,30})/g;
    HEAD_RE.lastIndex = 0;
    while ((m = HEAD_RE.exec(norm))) {
      const name = m[1].trim();
      if (!name || seen.has(name) || isNoiseName(name)) continue;
      const seg = norm.slice(m.index + m[0].length, m.index + m[0].length + 220);
      if (!/(活动时间|活动期间|开放时间|开启时间|挑战时间)/.test(seg.slice(0, 120))) continue;
      const [s, e] = rangeInSeg(seg, ref);
      if (s || e) { seen.add(name); out.push([name, s, e]); }
    }
    return out;
  }

  /* ---------- 绝区零版本公告专用活动解析 ---------- */
  // 米哈游版本公告正文里,活动列在「七、全新活动」章节,格式:
  // · 活动名
  //   活动描述...
  //   活动时间:2026/08/07 10:00(服务器时间) ~ 2026/08/24 03:59(服务器时间)
  function zzzExtractEvents(html, verStart, verEnd) {
    if (!html) return [];
    // 保留段落结构:块级标签替换为换行,再清理其他标签
    const text = html.replace(/<\/(?:p|div|li|h[1-6]|tr|br)\s*>/gi, '\n')
      .replace(/<[^>]+>/g, ' ').replace(/&\w+;/g, ' ')
      .replace(/\n\s*/g, '\n').replace(/[ \t]+/g, ' ').trim();
    const out = [], seen = new Set();
    // 定位「七、全新活动」章节;后面可能还有「八、全新玩法」等,只取到下一章
    const secMatch = /[七7][\s、.．]+全新活动/.exec(text);
    if (!secMatch) return out;
    const rest = text.slice(secMatch.index + secMatch[0].length);
    const nextSec = /(?:^|\n)\s*[八九九十][\s、.．]+全新/.exec(rest);
    const section = nextSec ? rest.slice(0, nextSec.index) : rest;
    // 匹配 · 活动名 行
    const itemRe = /(?:^|\n)\s*[·\-•]\s*([^\n]{2,35}?)(?=\n|$)/g;
    let m;
    while ((m = itemRe.exec(section))) {
      const name = m[1].replace(/\s+/g, ' ').trim();
      if (!name || seen.has(name) || isNoiseName(name)) continue;
      // 在该条目之后 600 字符内找活动时间
      const tail = section.slice(m.index + m[0].length, m.index + m[0].length + 600);
      const timeMatch = /活动时间[:：]([^\n]+)/.exec(tail);
      if (!timeMatch) continue;
      const timeStr = normText(timeMatch[1].trim());
      // 解析两种形式:
      // 1) 2026/08/07 10:00(服务器时间) ~ 2026/08/24 03:59(服务器时间)
      // 2) 3.1版本更新后 ~ 3.1版本结束 / 2026/09/08 03:59(服务器时间)
      const dtRe = /(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})/g;
      const dates = []; let dm;
      while ((dm = dtRe.exec(timeStr))) dates.push(new Date(+dm[1], +dm[2]-1, +dm[3], +dm[4], +dm[5]));
      let s = dates[0] || null, e = dates[1] || null;
      // 缺失日期用版本起止时间兜底
      if (/版本更新后|版本维护后|更新后|维护结束/.test(timeStr)) {
        if (!s) s = verStart || null;
        else if (!e) { e = s; s = verStart || null; }  // 「版本更新后 ~ 单日期」:该日期是结束时间
      }
      if (!e && /版本结束/.test(timeStr)) e = verEnd || null;
      if (!s && !e) continue;
      seen.add(name); out.push([name, s, e]);
    }
    return out;
  }

  /* ---------- 米哈游系:游戏内公告(真实活动排期) ---------- */
  const MIHOYO_ANN = {
    hsr: ['https://hkrpg-ann-api.mihoyo.com/common/hkrpg_cn/announcement/api/getAnnList',
      'bundle_id=hkrpg_cn&channel_id=1&game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&level=70&platform=pc&region=prod_gf_cn&uid=100000000',
      'https://sdk.mihoyo.com/hkrpg/announcement/index.html?auth_appid=announcement&authkey_ver=1&bundle_id=hkrpg_cn&channel_id=1&game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&level=70&platform=pc&region=prod_gf_cn&sign_type=2&uid=100000000'],
    zzz: ['https://announcement-api.mihoyo.com/common/nap_cn/announcement/api/getAnnList',
      'bundle_id=nap_cn&channel_id=1&game=nap&game_biz=nap_cn&lang=zh-cn&level=60&platform=pc&region=prod_gf_cn&uid=100000000',
      'https://sdk.mihoyo.com/nap/announcement/index.html?auth_appid=announcement&authkey_ver=1&bundle_id=nap_cn&channel_id=1&font_option=light&game=nap&game_biz=nap_cn&lang=zh-cn&level=60&platform=pc&region=prod_gf_cn&sign_type=2&uid=100000000'],
  };
  function annDt(s) {
    const m = /(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(s || '');
    return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
  }
  async function mihoyoContent(api, params, annId) {
    try {
      const d = await httpJson(`${api.replace('getAnnList', 'getAnnContent')}?${params}&ann_id=${annId}`);
      const lst = ((d.data || {}).list) || [];
      return lst.length ? (lst[0].content || '') : (((d.data || {}).content) || '');
    } catch (e) { return ''; }
  }
  async function mihoyo(gid, gname) {
    const [api, params, link] = MIHOYO_ANN[gid];
    const d = await httpJson(`${api}?${params}`);
    const groups = ((d.data || {}).list) || [];
    const now = new Date();
    const out = [];
    let verDone = false;  // 只拆最新一期版本说明文
    for (const g of groups) {
      const typeLabel = g.type_label || '';
      if (typeLabel.includes('推荐')) continue;  // 推荐页签多为周边/广告,丢弃
      for (const a of (g.list || [])) {
        let title = a.title || '';
        if (title.includes('<')) title = a.subtitle || htmlToText(title);
        title = title.replace(/\s+/g, ' ').trim();
        if (!title) continue;
        const start = annDt(a.start_time), end = annDt(a.end_time);
        if (start && end && (end - start) / 864e5 > 400) continue;      // 常驻
        if (end && (now - end) / 864e5 > 30) continue;                  // 旧条目
        // 版本更新说明:拆全文提取活动/角色与专武排期,文章本身不进日历
        if (!verDone && VER_NOTE_RE.test(title) && a.ann_id) {
          const raw = await mihoyoContent(api, params, a.ann_id);
          // 真版本说明文必含「全新活动」章节;HSR接口偶发错返回通行证等内容,跳过
          if (raw && raw.includes('全新活动')) {
            verDone = true;
            // 绝区零解析依赖块级标签还原换行,必须喂原始 HTML;
            // 星铁走通用提取,先转纯文本
            const items = gid === 'zzz'
              ? zzzExtractEvents(raw, start || now, end)
              : extractEvents(htmlToText(raw), start || now);
            for (const [name, s, e] of items) {
              if (e && e < now) continue;
              if (BAD_SHORT.has(name) || name.length < 3) continue;
              const c2 = classify(name, '活动');
              out.push(ev(gid, gname, name, (c2 === '活动' || c2 === '角色与专武') ? c2 : '活动',
                start || now, s, e, link, '', 'event'));
            }
          }
        }
        const tag = (a.tag_label || '') + typeLabel;
        // 分级判定(优先级: 噪音 > 商城 > 卡池 > 活动 > 其他)
        let cat, kind;
        // 绝区零服务端把很多地点/角色/系统说明标为"活动",需用黑名单二次过滤
        const isZzzNonEvent = gid === 'zzz' && ZZZ_NON_EVENT.has(title);
        if (isZzzNonEvent || NOISE_RE.test(title)) { cat = '资讯'; kind = 'info'; }
        else if (SHOP_RE.test(title)) { cat = '公告'; kind = 'info'; }
        else if (POOL_RE.test(tag) || POOL_RE.test(title)) { cat = '角色与专武'; kind = 'event'; }
        else if (gid === 'zzz' && /(活动公告|福利活动|卡池公告)/.test(a.tag_label) && start && end) {
          // 绝区零:独立公告里只认明确的活动/卡池/福利标签,杜绝地区/时装/系统混入
          // (卡池已在上一分支兜住,这里只需排除商城/网页类)
          if (SHOP_RE.test(title) || WEB_RE.test(title)) { cat = '资讯'; kind = 'info'; }
          else { cat = '活动'; kind = 'event'; }
        }
        else if ((typeLabel.includes('活动') || ACT_TITLE_RE.test(title)) && start && end) {
          if (WEB_RE.test(title)) { cat = '资讯'; kind = 'info'; }
          else { cat = '活动'; kind = 'event'; }
        } else { cat = classify(title, '公告'); kind = 'info'; }
        out.push(ev(gid, gname, title, cat, start || now, start, end, link, a.banner || '', kind, a.ann_id ? { ann_id: a.ann_id, api, params } : null));
      }
    }
    return out;
  }

  /* ---------- 明日方舟:终末地 ---------- */
  const EF_T_RE = /(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})/g;
  // 版本更新说明:按「■ 全新寻访及申领 / ■ 全新活动」章节拆排期,返回 [[name,cat,start,end]]
  function efExtractVersion(text, pub) {
    let verStart = pub;  // 版本开服时间 = 维护时段的结束时间
    const vm = /(\d{4})\/(\d{2})\/(\d{2}) \d{2}:\d{2}\s*-\s*(\d{4})\/(\d{2})\/(\d{2}) (\d{2}):(\d{2})\s*（UTC\+8）/.exec(text);
    if (vm) verStart = new Date(+vm[4], +vm[5] - 1, +vm[6], +vm[7], +vm[8]);
    const dates = seg => {
      const out = []; let m; EF_T_RE.lastIndex = 0;
      while ((m = EF_T_RE.exec(seg))) out.push(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
      // 兜底:识别「月日」「月日 点」等其它写法,并修正跨年区间
      for (const t of findDateTokens(seg, pub)) {
        if (!out.some(o => Math.abs(o - t.dt) < 36e5)) out.push(t.dt);
      }
      out.sort((a, b) => a - b);
      return out;
    };
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    const out = [];
    let section = '', lastName = '';
    const now = new Date();
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (l.startsWith('■') || l.startsWith('▼')) { section = l; continue; }
      if (!['寻访', '申领', '活动', '赛季'].some(k => section.includes(k))) continue;
      const tm = /^[·•]?\s*(活动时间|开放时间|赛季更新)[:：]\s*(.*)$/.exec(l);
      if (!tm && l.includes('「') && !l.startsWith('※')) {
        const nm = /「([^」]{2,24})」/.exec(l);
        if (nm) lastName = nm[1];
      }
      if (!tm) continue;
      let segs = [tm[2]];
      if (dates(segs[0]).length === 0) {  // 时间写在下一行(多期活动)
        segs = [];
        let j = i + 1;
        while (j < lines.length && dates(lines[j]).length) { segs.push(lines[j]); j++; }
      }
      for (const seg of segs) {
        if (/长期开放|常驻|长期有效/.test(seg) || seg.includes('次「特许寻访」')) continue;  // 常驻/特殊规则池不上排期
        const ds = dates(seg);
        let start, end;
        if (seg.includes('版本更新后')) { start = verStart; end = ds[0] || null; }
        else if (ds.length) { start = ds[0]; end = ds.length > 1 ? ds[1] : null; }
        else continue;
        if (!lastName || (end && end < now)) continue;
        const cat = (section.includes('寻访') || section.includes('申领')) ? '角色与专武' : '活动';
        out.push([lastName, cat, start, end]);
      }
    }
    return out;
  }
  async function endfield(gid, gname) {
    const html = await httpText('https://endfield.hypergryph.com/news');
    // 文章ID在 self.__next_f 流式数据中: \"cid\":\"9335\",...,\"title\":\"...\"
    const cidOf = new Map();
    const unesc = html.replace(/\\"/g, '"');
    const cre = /"cid":"(\d+)"[^}]{0,400}?"title":"((?:[^"\\]|\\.)*?)"/g;
    let cm;
    while ((cm = cre.exec(unesc))) cidOf.set(cm[2].replace(/\s+/g, ' ').trim(), cm[1]);
    const pat = /NoticeList_item__\w+"[^>]*>.*?<img src="([^"]+)" alt="([^"]*)".*?NoticeList_type__\w+">([^<]+)<\/span>.*?NoticeList_date__\w+">([\d.]+)<\/span>.*?NoticeList_title__\w+">([^<]+)<\/div>/gs;
    const out = [];
    let m, verDone = false;  // 只拆最新一期版本说明文
    while ((m = pat.exec(html))) {
      const [, img, , typ, dateS, rawTitle] = m;
      const title = rawTitle.trim();
      const dm = /(\d{4})\.(\d{2})\.(\d{2})/.exec(dateS.trim());
      const pub = dm ? new Date(+dm[1], +dm[2] - 1, +dm[3]) : new Date();
      const cid = cidOf.get(title);
      const link = cid ? `https://endfield.hypergryph.com/news/${cid}` : 'https://endfield.hypergryph.com/news';
      // 版本更新说明:内含全新活动/寻访及申领排期,拆出为独立事件
      if (!verDone && VER_NOTE_RE.test(title)) {
        verDone = true;
        try {
          const raw = (await httpText(link))
            .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/g, ' ');
          const text = raw.replace(/<[^>]+>/g, '\n').replace(/&\w+;/g, ' ');
          for (const [name, cat, s, e] of efExtractVersion(text, pub)) {
            out.push(ev(gid, gname, name, cat, pub, s, e, link, '', 'event'));
          }
        } catch (e) { }
      }
      const cat = classify(title, typ.includes('活动') ? '活动' : (typ.includes('公告') ? '公告' : '资讯'));
      const kind = (cat === '活动' || cat === '角色与专武') && !NOISE_RE.test(title) ? 'event' : 'info';
      out.push(ev(gid, gname, title, cat, pub, null, null, link, img, kind));
    }
    return out;
  }

  /* ---------- 鸣潮 ---------- */
  async function wuthering(gid, gname) {
    const arr = await httpJson('https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/ArticleMenu.json');
    arr.sort((a, b) => (b.startTime || '').localeCompare(a.startTime || ''));
    const out = [];
    let extracted = false;  // 只从最新一期版本说明文批量提取,避免历史版本活动刷屏
    for (const a of arr.slice(0, 60)) {
      const title = (a.articleTitle || '').trim();
      let pub = new Date();
      const pm = /(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(a.startTime || '');
      if (pm) pub = new Date(+pm[1], +pm[2] - 1, +pm[3], +pm[4], +pm[5]);
      const link = `https://mc.kurogame.com/main/news/detail/${a.articleId}`;
      if (!extracted && /内容说明/.test(title)) {
        extracted = true;
        try {
          const full = await httpJson(`https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/article/${a.articleId}.json`);
          const text = htmlToText(full.articleContent || '');
          const now = new Date();
          for (const [name, start, end] of extractEvents(text, pub)) {
            if (end && end < now) continue;  // 只保留未结束的活动
            out.push(ev(gid, gname, name, classify(name, '活动'), pub, start, end, link));
          }
        } catch (e) { }
      }
      const text = htmlToText(a.articleContent || '');
      const [start, end] = extractRange(text, pub);
      let cat = classify(title, a.articleType === 52 ? '公告' : '活动');
      // 官网文章只有「唤取/卡池」类且有排期才上月历,其余文章均为资讯
      let kind;
      if (POOL_RE.test(title) && start) { cat = '角色与专武'; kind = 'event'; }
      else if ((cat === '活动' || cat === '角色与专武') && start && end && !NOISE_RE.test(title)) kind = 'event';
      else kind = 'info';
      out.push(ev(gid, gname, title, cat, pub, start, end, link, '', kind));
    }
    return out;
  }

  /* ---------- 异环 ---------- */
  const AN_TIME_KW = /(活动时间|开放时间|开启时间)[:：]\s*([^。●]{0,60})/g;
  const AN_DATE = /(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})[:：](\d{2}))?/g;
  // 版本更新/停服维护公告:找全部时间规格,名字取前面最近的「」/【】,返回 [[name,cat,start,end]]
  function anantaExtractVersion(text, pub) {
    let verStart = pub;  // 版本开服时间 = 维护时段的结束时间
    const vm = /(\d{1,2})月(\d{1,2})日(\d{1,2})[:：](\d{2})\s*[–—\-~]\s*(\d{1,2})[:：](\d{2})\s*进行(?:停服|版本更新)?维护/.exec(text);
    if (vm) verStart = new Date(pub.getFullYear(), +vm[1] - 1, +vm[2], +vm[5], +vm[6]);
    const dates = seg => {
      const out = []; let m; AN_DATE.lastIndex = 0;
      while ((m = AN_DATE.exec(seg))) {
        const d = new Date(pub.getFullYear(), +m[1] - 1, +m[2], m[3] ? +m[3] : 0, m[4] ? +m[4] : 0);
        if ((d - pub) / 864e5 < -10) d.setFullYear(d.getFullYear() + 1);  // 早于公告发布日 = 跨年
        out.push(d);
      }
      // 兜底:识别「x年x月x日」等其它写法
      for (const t of findDateTokens(seg, pub)) {
        if ((t.dt - pub) / 864e5 < -10) t.dt.setFullYear(t.dt.getFullYear() + 1);
        if (!out.some(o => Math.abs(o - t.dt) < 36e5)) out.push(t.dt);
      }
      out.sort((a, b) => a - b);
      return out;
    };
    const now = new Date(), out = [], seen = new Set();
    let tm; AN_TIME_KW.lastIndex = 0;
    while ((tm = AN_TIME_KW.exec(text))) {
      const seg = tm[2];
      if (/长期|常驻|永久/.test(seg)) continue;  // 常驻内容不上排期
      const ds = dates(seg);
      let start, end;
      if (seg.includes('更新后')) {
        const ends = ds.filter(d => d > verStart);
        if (!ends.length) continue;  // 仅「版本更新后」无结束时间 = 常驻内容
        start = verStart; end = ends[ends.length - 1];
      } else if (ds.length) {
        start = ds[0]; end = ds.length > 1 ? ds[1] : null;
      } else continue;
      if (end && end < start) end = new Date(end.getFullYear() + 1, end.getMonth(), end.getDate(), end.getHours(), end.getMinutes());
      if (!end || end < now) continue;
      // 名字: 时间关键字前最近的一个「」/【】(不跨句号/条目符)
      const ctx0 = Math.max(text.lastIndexOf('。', tm.index), text.lastIndexOf('●', tm.index)) + 1;
      const ctx = text.slice(ctx0, tm.index);
      const names = [...ctx.matchAll(/「([^」]{2,24})」|【([^】]{2,24})】/g)];
      if (!names.length) continue;
      const nm = names[names.length - 1];
      const name = (nm[1] || nm[2]).trim();
      const blob = ctx + seg;
      if (/折扣价格|在售时间|上架商城|商城购买|涂装价格|礼包/.test(blob)) continue;  // 商城时装/礼包不上排期
      const cat = /限定S级|研募/.test(blob) ? '角色与专武' : '活动';
      const key = name + '|' + start.getTime();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push([name, cat, start, end]);
    }
    return out;
  }
  async function ananta(gid, gname) {
    const seen = new Set();
    const entries = [];  // {title, pub, link, dft}
    for (const [cat, dft] of [['gameevent', '活动'], ['gamebroad', '公告'], ['gamenews', '资讯']]) {
      const html = await httpText(`https://yh.wanmei.com/news/${cat}/index.html`);
      const pat = /<a href="(\/news\/\w+\/\d+\/\d+\.html)"[^>]*>\s*<div class="listItem">.*?<h2 class="title">(.*?)<\/h2>.*?<p class="date">([\d-]+)<\/p>\s*<p class="type">([^<]*)<\/p>/gs;
      let m, n = 0;
      while ((m = pat.exec(html)) && n < 5) {
        const [, href, rawTitle, dateS] = m;
        if (seen.has(href)) continue;
        seen.add(href); n++;
        const title = rawTitle.replace(/<[^>]+>|\s+/g, ' ').trim();
        const dm = /(\d{4})-(\d{2})-(\d{2})/.exec(dateS.trim());
        const pub = dm ? new Date(+dm[1], +dm[2] - 1, +dm[3]) : new Date();
        entries.push({ title, pub, link: 'https://yh.wanmei.com' + href, dft });
      }
    }
    // 并行抓详情页
    const texts = new Map();
    await Promise.all(entries.filter(e => e.dft !== '资讯').map(async e => {
      try { texts.set(e.link, htmlToText(await httpText(e.link))); } catch (err) { }
    }));
    const out = [];
    let verN = 0;  // 只拆最新两期版本/维护公告(上半+下半)
    for (const { title, pub, link, dft } of entries) {
      let start = null, end = null;
      const text = texts.get(link);
      if (text) {
        [start, end] = extractRange(text, pub);
        // 版本/维护公告:内含卡池与限时活动排期,拆出为独立事件
        if (verN < 2 && /更新公告|维护公告/.test(title)) {
          verN++;
          for (const [name, cat2, s, e] of anantaExtractVersion(text, pub)) {
            out.push(ev(gid, gname, name, cat2, pub, s, e, link, '', 'event'));
          }
        }
      }
      const cat = classify(title, dft);
      const kind = (cat === '活动' || cat === '角色与专武') && !NOISE_RE.test(title) ? 'event' : 'info';
      if (end && (Date.now() - end) / 864e5 > 30) continue;  // 结束超30天的旧活动丢弃
      out.push(ev(gid, gname, title, cat, pub, start, end, link, '', kind));
    }
    return out;
  }

  /* ---------- 调度 ---------- */
  const RUNNERS = {
    hsr:       () => mihoyo('hsr', '崩坏：星穹铁道'),
    zzz:       () => mihoyo('zzz', '绝区零'),
    endfield:  () => endfield('endfield', '明日方舟：终末地'),
    wuwa:      () => wuthering('wuwa', '鸣潮'),
    ananta:    () => ananta('ananta', '异环'),
  };

  /* ---------- B站官号动态(公开接口,免签名) ---------- */
  const BILI_UIDS = [
    ['hsr', '崩坏：星穹铁道', 1340190821],
    ['zzz', '绝区零', 1636034895],
    ['endfield', '明日方舟：终末地', 1265652806],
    ['wuwa', '鸣潮', 1955897084],
    ['ananta', '异环', 3546636978489848],
  ];
  const BILI_NOISE = /生日快乐|生日祝福|早安|晚安/;
  const BILI_HOT = /抽奖|活动|福利|预约|直播|前瞻|征稿|征集|联动|测试|签到|开启|版本|维护|更新/;
  const BILI_TAG = /#[^#\r\n]+#/g;

  async function biliJson(url) {
    for (let i = 0; i < 2; i++) {
      try {
        const r = await fetch(url);
        if (r.ok) {
          const t = await r.text();
          if (t.trim().startsWith('{')) return JSON.parse(t);
        }
      } catch (e) { }
      await new Promise(r => setTimeout(r, 400));
    }
    return null;
  }
  function biliTitle(clean) {
    const lines = clean.split('\n').map(s => s.trim().replace(/^[,，。. ]+|[,，。. ]+$/g, '')).filter(Boolean);
    if (!lines.length) return '';
    let t = lines[0];
    if (t.length < 8 && lines.length > 1) t = t + ' ' + lines[1];
    return t.length > 38 ? t.slice(0, 38) + '…' : t;
  }
  async function bilibiliAll(perGame) {
    const events = [], errs = [];
    for (const [gid, gname, uid] of BILI_UIDS) {
      try {
        // 完整动态流(带时间戳,可能失败,尽力而为)
        const tmap = new Map();
        const fd = await biliJson(`https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=${uid}`);
        for (const it of (((fd || {}).data || {}).items || [])) {
          const ts = (((it.modules || {}).module_author) || {}).pub_ts;
          if (it.id_str && ts) tmap.set(it.id_str, +ts);
        }
        // 图文动态(稳定)
        const d = await biliJson(`https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space?host_mid=${uid}&page_num=0&page_size=${Math.max(perGame, 6)}`);
        const items = (((d || {}).data || {}).items || []).slice(0, perGame);
        for (const it of items) {
          const text = (it.content || '').trim();
          if (!text) continue;
          const clean = text.replace(BILI_TAG, '').trim();
          const title = biliTitle(clean);
          if (!title) continue;
          if (BILI_NOISE.test(title) && !BILI_HOT.test(clean)) continue;
          const flat = clean.replace(/\s+/g, ' ');
          const [start, end] = extractRange(flat, new Date());
          const ts = tmap.get(it.opus_id);
          const pub = ts ? new Date(ts * 1000) : (start || new Date());
          const cat = classify(title, BILI_HOT.test(clean) ? '活动' : '资讯');
          let img = ((it.cover || {}).url) || '';
          if (img.startsWith('http://')) img = 'https://' + img.slice(7);
          let link = it.jump_url || '';
          if (link.startsWith('//')) link = 'https:' + link;
          const e = ev(gid, gname, title, cat, pub, start, end, link || `https://space.bilibili.com/${uid}/dynamic`, img, 'info');
          e.src = 'bilibili';  // B站动态一律不上月历
          events.push(e);
        }
      } catch (e) {
        errs.push(`${gname}: ${String(e).slice(0, 60)}`);
      }
      await new Promise(r => setTimeout(r, 300));
    }
    return { events, status: { name: 'B站动态', ok: !errs.length, count: events.length, error: errs.join('; ').slice(0, 150) } };
  }

  /* ---------- 手动事件(安卓端从 localStorage 读) ---------- */
  function manualEvents() {
    try {
      const arr = JSON.parse(localStorage.getItem('ycal_manual') || '[]');
      const names = Object.fromEntries(GAMES.map(g => [g.id, g.name]));
      // 与 Python 端一致:无 title 的说明性条目跳过
      return (arr || []).filter(e => e && e.title).map((e, i) => ({
        id: `manual-${i}`,
        game_id: e.game_id || '',
        game: names[e.game_id] || e.game || '自定义',
        title: e.title || '未命名事件',
        category: e.category || '活动',
        start: e.start || null,
        end: e.end || null,
        date: e.start || iso(new Date()),
        link: e.link || '',
        image: e.image || '',
        src: 'manual',
        kind: e.kind || 'event',  // 手动填入默认上月历
      }));
    } catch (e) { return []; }
  }

  /* ---------- 后置活动校验:多维度判断条目是否配上月历 ---------- */
  // 从官方 API 抓到的条目未必是真活动——可能是玩法说明、系统公告、更新日志等
  // 返回 {valid, reason}, valid=false 的条目降级为 info(只在资讯列表,不进日历)
  const VALID_DURATION = { minH: 2, maxH: 90 * 24 };  // 合理活动时长:2小时~90天(放行同日直播/限时闪购)
  const NON_EVENT_TITLE = /说明$|指南$|攻略$|规则$|介绍$|一览$|公示$|回顾$/;  // 说明书类标题
  const EVENT_FEATURE_RE = /活动(?![说指解规一]).{0,12}(?:开启|开放|上线|开始)|「[^」]+」|限时|版本活动|新版|全新/;  // 真活动常有的特征:活动名+时间动词

  function validateEvent(e) {
    // 0) kind='info' 本身就不上月历,无需校验
    if (e.kind !== 'event') return { valid: true, reason: '' };

    const title = e.title || '';
    const name = title;  // already shortTitle

    // 1) 标题含说明书语气→非活动
    if (NON_EVENT_TITLE.test(title))
      return { valid: false, reason: '标题像说明书(说明/指南/规则/介绍/一览/公示/回顾结尾)' };

    // 1.5) 标题以「活动时间:」「开放时间:」等正文串味开头→非活动
    if (/^(活动时间|开放时间|开启时间)[:：]/.test(title))
      return { valid: false, reason: '标题是正文时间串(活动时间:/开放时间:开头)' };

    // 2) 标题过于简短(<2字)且非卡池词→非活动
    if (name.length < 2 && !/祈愿|跃迁|寻访|唤取|调频/.test(title))
      return { valid: false, reason: `标题过短(${name.length}字)` };

    // 3) 标题是(或仅含)已过滤的噪音名→非活动
    if (isNoiseName(name) || isNoiseName(title.slice(0, 30)))
      return { valid: false, reason: '标题是噪音通用名' };

    // 4) 有开始和结束时间:检查时长是否合理(按小时计,放行同日短活动)
    if (e.start && e.end) {
      const durH = (new Date(e.end) - new Date(e.start)) / 36e5;
      if (durH < VALID_DURATION.minH)
        return { valid: false, reason: `活动时长过短(${durH.toFixed(1)}小时)` };
      if (durH > VALID_DURATION.maxH)
        return { valid: false, reason: `活动时长过长(${Math.round(durH / 24)}天,可能是常驻)` };
    }

    // 5) 无起止时间的条目:需要更强的活动特征才上月历
    if (!e.start) {
      if (!EVENT_FEATURE_RE.test(title))
        return { valid: false, reason: '非官方来源且缺乏活动特征词' };
    }

    // 6) 标题命中噪音词→降级
    if (NOISE_RE.test(title))
      return { valid: false, reason: `标题命中噪音词:${title.match(NOISE_RE)[0]}` };

    // 7) 商城/网页/H5活动不上月历
    if (SHOP_RE.test(title) || WEB_RE.test(title))
      return { valid: false, reason: '商城/网页活动不排期' };

    return { valid: true, reason: '' };
  }

  async function fetchAll(onProgress) {
    _uid = 0;
    const events = [], sources = {};
    const jobs = GAMES.map(async g => {
      const t0 = Date.now();
      if (onProgress) onProgress(`正在抓取 ${g.name}…`);
      try {
        const evs = await RUNNERS[g.id]();
        events.push(...evs);
        sources[g.id] = { name: g.name, ok: true, count: evs.length, took: (Date.now() - t0) / 1000 };
      } catch (e) {
        sources[g.id] = { name: g.name, ok: false, count: 0, error: String(e).slice(0, 120), took: (Date.now() - t0) / 1000 };
      }
    });
    await Promise.allSettled(jobs);
    // B站动态
    try {
      if (onProgress) onProgress('正在抓取 B站动态…');
      const t0 = Date.now();
      const b = await bilibiliAll(6);
      events.push(...b.events);
      sources.bilibili = { ...b.status, took: (Date.now() - t0) / 1000 };
    } catch (e) {
      sources.bilibili = { name: 'B站动态', ok: false, count: 0, error: String(e).slice(0, 120) };
    }
    // 手动事件
    events.push(...manualEvents());
    // 去重(同游戏同标题):手动录入条目经人工核实,优先保留
    const seen = new Map();
    for (const e of events) {
      const key = e.game_id + '|' + e.title;
      const old = seen.get(key);
      if (!old || (e.src === 'manual' && old.src !== 'manual') || (!old.start && e.start)) seen.set(key, e);
    }
    // 后置校验:对每个 event 做质量检查,不通过→降级为 info(不进月历)
    let dropped = 0;
    for (const e of seen.values()) {
      if (e.kind === 'event') {
        const r = validateEvent(e);
        if (!r.valid) {
          e.kind = 'info';
          e._reject = r.reason;
          dropped++;
        }
      }
    }
    if (dropped > 0) console.log(`[validateEvent] ${dropped} 个条目降级(非真活动)`);

    const list = [...seen.values()].sort((a, b) => (b.start || b.date || '').localeCompare(a.start || a.date || ''));
    const now = new Date();
    return { events: list, sources, games: GAMES, updated: iso(now) };
  }

  return { GAMES, fetchAll };
})();
