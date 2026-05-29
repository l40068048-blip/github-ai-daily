#!/usr/bin/env python3
"""
GitHub AI 日报 - 每天获取 GitHub 上最新的 AI 相关热门仓库
支持中文翻译 + 推送到微信（PushPlus / Server酱）

用法:
    python github_ai_daily.py                         # 终端显示 + 保存文件
    python github_ai_daily.py --push                  # 推送微信（中文翻译）
    python github_ai_daily.py --pushplus 你的Token     # 指定 PushPlus
    python github_ai_daily.py --no-translate           # 不翻译，保持英文
"""

import requests
import re
import sys
import os
import argparse
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser

# ============================================================
# 配置
# ============================================================

TRENDING_URL = "https://github.com/trending?since=daily"

# AI/ML 相关关键词
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "chatgpt", "openai", "claude",
    "rag", "agent", "autogpt", "langchain", "vectordb", "embedding",
    "stable diffusion", "diffusion", "transformer", "neural network",
    "computer vision", "nlp", "natural language", "speech recognition",
    "tensorflow", "pytorch", "llama", "mistral", "gemma", "qwen",
    "chatbot", "copilot", "agi", "multimodal", "vision language",
    "yolo", "object detection", "segmentation", "ocr",
    "fine-tuning", "rlhf", "reinforcement learning",
    "data science", "predictive", "recommendation",
    "whisper", "tts", "text to speech",
    "knowledge graph", "semantic",
    "prompt", "prompt engineering", "tokenizer",
    "gen ai", "generative ai", "foundation model",
    "mcp", "model context protocol",
]

EXCLUDE_KEYWORDS = ["ai generated", "ai writing", "去除ai"]


# ============================================================
# 翻译（免费 MyMemory API）
# ============================================================

_translation_cache = {}

def translate_text(text, target="zh-CN"):
    """将英文翻译成中文，使用 MyMemory 免费 API"""
    if not text or len(text.strip()) < 3:
        return text
    
    # 如果已经是中文，不翻译
    if re.search(r'[\u4e00-\u9fff]', text):
        return text
    
    # 缓存命中
    cache_key = (text, target)
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]
    
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text[:500],  # API 限制长度
            "langpair": f"en|{target}",
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data.get("responseStatus") == 200:
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated:
                # 解码 HTML 实体（如 &#39; → '）
                translated = translated.replace("&#39;", "'").replace("&amp;", "&")
                _translation_cache[cache_key] = translated
                return translated
        
        return text  # 翻译失败，返回原文
    except Exception:
        return text  # 出错时返回原文


def translate_description(desc):
    """翻译仓库描述，智能处理混合内容"""
    if not desc:
        return ""
    # 如果已含中文，不翻译
    if re.search(r'[\u4e00-\u9fff]', desc):
        return desc
    return translate_text(desc)


# ============================================================
# HTML 解析器
# ============================================================

class TrendingParser(HTMLParser):
    """解析 GitHub Trending 页面"""

    def __init__(self):
        super().__init__()
        self.repos = []
        self._in_article = False
        self._curr = {}
        self._in_h2 = False
        self._in_desc_p = False
        self._in_topic = False
        self._field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'article' and 'class' in a:
            if 'Box-row' in a['class'].split():
                self._in_article = True
                self._curr = {}
        if not self._in_article:
            return
        if tag == 'h2':
            self._in_h2 = True
            self._field = 'name'
        elif tag == 'a' and self._in_h2:
            href = a.get('href', '')
            if href.startswith('/') and '/' in href[1:]:
                self._curr['full_name'] = href.strip('/')
        elif tag == 'p' and 'col-9' in a.get('class', '').split():
            self._in_desc_p = True
            self._field = 'description'
        elif tag == 'a' and 'topic-tag' in a.get('class', '').split():
            self._in_topic = True
            self._field = 'topics'

    def handle_data(self, data):
        if not (self._in_article and self._field):
            return
        text = data.strip()
        if not text:
            return
        if self._field == 'name':
            display = text.replace('\n', '').strip()
            if display:
                self._curr['display_name'] = display
        elif self._field == 'description':
            if 'description' not in self._curr:
                self._curr['description'] = text
        elif self._field == 'topics':
            if 'topics' not in self._curr:
                self._curr['topics'] = []
            self._curr['topics'].append(text)

    def handle_endtag(self, tag):
        if not self._in_article:
            return
        if tag == 'h2':
            self._in_h2 = False
            self._field = None
        elif tag == 'p' and self._field == 'description':
            self._in_desc_p = False
            self._field = None
        elif tag == 'a' and self._in_topic:
            self._in_topic = False
            self._field = None
        elif tag == 'article':
            fn = self._curr.get('full_name', '')
            dn = self._curr.get('display_name', '')
            if fn and not dn:
                self._curr['display_name'] = fn.split('/')[-1]
            if fn:
                self.repos.append(self._curr)
            self._in_article = False
            self._curr = {}
            self._field = None


# ============================================================
# 获取数据
# ============================================================

def fetch_trending():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }
    try:
        resp = requests.get(TRENDING_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"❌ 获取 Trending 页面失败: {e}")
        return None


def parse_repos(html):
    parser = TrendingParser()
    parser.feed(html)
    return parser.repos


# ============================================================
# AI 筛选
# ============================================================

def is_ai_related(repo):
    text_parts = []
    for key in ('full_name', 'display_name', 'description', 'topics'):
        val = repo.get(key)
        if isinstance(val, str):
            text_parts.append(val.lower())
        elif isinstance(val, list):
            text_parts.extend(v.lower() for v in val)
    text = ' '.join(text_parts)
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text:
            return False
    for kw in AI_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


# ============================================================
# 报告生成
# ============================================================

def format_console_report(ai_repos, total_repos):
    """终端显示（保持英文，原汁原味）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "=" * 72,
        f"  🤖  GitHub AI 日报  |  {today}",
        "=" * 72,
        "",
        f"  📊 今日热门仓库共 {total_repos} 个，其中 AI 相关 {len(ai_repos)} 个",
        "",
    ]
    if not ai_repos:
        lines += ["  ⚠️  今日未识别到 AI 相关热门项目", ""]
    else:
        for i, repo in enumerate(ai_repos[:25], 1):
            fn = repo.get('full_name', '?')
            desc = repo.get('description', '') or ''
            topics = repo.get('topics', [])
            topic_tags = ' '.join(f'#{t}' for t in topics[:6])
            lines.append(f"  {'─' * 70}")
            lines.append(f"  [{i:2d}] {fn}")
            if desc:
                if len(desc) > 85:
                    desc = desc[:82] + '...'
                lines.append(f"       📝 {desc}")
            if topic_tags:
                lines.append(f"       🏷️  {topic_tags}")
    lines += [
        "",
        f"  {'=' * 72}",
        f"  💡 完整榜单: https://github.com/trending?since=daily",
        f"  {'=' * 72}",
        "",
    ]
    return '\n'.join(lines)


def build_push_content(ai_repos, total_repos, translate=True):
    """生成微信推送内容（带中文翻译）"""
    today = datetime.now(timezone.utc).strftime("%m-%d")
    lines = [f"🤖 GitHub AI 日报 | {today}"]
    lines.append(f"今日热门 {total_repos} 个，AI 相关 {len(ai_repos)} 个")
    lines.append("")
    
    for i, repo in enumerate(ai_repos[:12], 1):
        fn = repo.get('full_name', '?')
        desc = repo.get('description', '') or ''
        
        # 翻译描述
        if translate and desc:
            desc_cn = translate_description(desc)
            if desc_cn != desc:
                desc = f"{desc_cn}"
        
        lines.append(f"{i}. {fn}")
        if desc:
            d = desc[:80] + '...' if len(desc) > 80 else desc
            lines.append(f"   {d}")
        topics = repo.get('topics', [])
        if topics:
            lines.append(f"   {' '.join(f'#{t}' for t in topics[:3])}")
        lines.append("")
    
    lines.append(f"完整榜单: https://github.com/trending?since=daily")
    return '\n'.join(lines)


def build_push_markdown(ai_repos, total_repos, translate=True):
    """生成 Markdown 推送内容（带中文翻译）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = f"# 🤖 GitHub AI 日报 - {today}\n\n"
    md += f"> 今日热门 **{total_repos}** 个，AI 相关 **{len(ai_repos)}** 个\n\n---\n\n"
    
    for i, repo in enumerate(ai_repos[:12], 1):
        fn = repo.get('full_name', '?')
        desc = repo.get('description', '') or '暂无描述'
        
        # 翻译描述
        if translate and desc:
            desc_cn = translate_description(desc)
            if desc_cn != desc:
                desc = f"~~{desc}~~  \n{desc_cn}"
        
        topics = repo.get('topics', [])
        md += f"### {i}. [{fn}](https://github.com/{fn})\n\n{desc}\n\n"
        if topics:
            md += ' '.join(f'`{t}`' for t in topics[:5]) + '\n\n'
        md += "---\n\n"
    
    md += f"\n> [查看完整 Trending](https://github.com/trending?since=daily)"
    return md


def save_markdown(ai_repos, total_repos):
    """保存完整 Markdown 文件（中英双语，含翻译）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"github_ai_daily_{today}.md"
    
    md = f"""# 🤖 GitHub AI 日报 - {today}

> 每日自动生成，筛选自 [GitHub Trending](https://github.com/trending?since=daily)

---

## 📊 概览

| 指标 | 数值 |
|------|------|
| 今日热门仓库总数 | {total_repos} |
| AI 相关项目数 | {len(ai_repos)} |

---

## 🏆 AI 相关热门项目

"""
    for i, repo in enumerate(ai_repos[:25], 1):
        fn = repo.get('full_name', '?')
        desc = repo.get('description', '') or '暂无描述'
        topics = repo.get('topics', [])
        
        # 双语显示
        desc_cn = translate_description(desc)
        if desc_cn and desc_cn != desc:
            desc_display = f"{desc_cn}\n> {desc}"
        else:
            desc_display = desc
        
        md += f"### {i}. [{fn}](https://github.com/{fn})\n\n{desc_display}\n\n"
        if topics:
            md += ' '.join(f'`{t}`' for t in topics[:8]) + '\n\n'
        md += "---\n\n"
    
    md += f"""---

*数据来源: [GitHub Trending](https://github.com/trending?since=daily)*
*生成时间: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}*
"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(md)
    return filename


# ============================================================
# 推送渠道
# ============================================================

def push_serverchan(title, content, token):
    """Server酱·Turbo版"""
    if not token:
        print("⚠️  未提供 Server酱 SendKey")
        return False
    url = f"https://sctapi.ftqq.com/{token}.send"
    try:
        resp = requests.post(url, data={"title": title[:32], "desp": content}, timeout=15)
        r = resp.json()
        if r.get("code") == 0:
            print(f"✅ [Server酱] 推送成功！剩余: {r.get('data', {}).get('reset_free', '?')}次")
            return True
        else:
            print(f"❌ [Server酱] 推送失败: {r.get('message', '未知错误')}")
            return False
    except requests.RequestException as e:
        print(f"❌ [Server酱] 请求失败: {e}")
        return False


def push_pushplus(title, content, token):
    """PushPlus（推送加）- 国内稳定"""
    if not token:
        print("⚠️  未提供 PushPlus Token")
        return False
    url = "https://www.pushplus.plus/send"
    try:
        resp = requests.post(url, json={
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
        }, timeout=15)
        r = resp.json()
        if r.get("code") == 200:
            print(f"✅ [PushPlus] 推送成功！")
            return True
        else:
            print(f"❌ [PushPlus] 推送失败: {r.get('msg', '未知错误')}")
            return False
    except requests.RequestException as e:
        print(f"❌ [PushPlus] 请求失败: {e}")
        return False


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="🤖 GitHub AI 日报 - 每天获取 AI 相关热门仓库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
推送方式（推荐 PushPlus）:
  --pushplus TOKEN      通过 PushPlus 推送到微信（国内稳定）

翻译控制:
  --no-translate        保持英文，不翻译为中文
  (默认推送时自动翻译为中文)

环境变量:
  PUSHPLUS_TOKEN        设置 PushPlus Token
  SERVERCHAN_SENDKEY    设置 Server酱 SendKey

示例:
  python github_ai_daily.py                          # 终端查看
  python github_ai_daily.py --pushplus 你的Token      # 推送中文到微信
  python github_ai_daily.py --push --no-translate     # 推送英文
        """
    )
    parser.add_argument('--push', action='store_true',
                       help='推送微信（自动检测 PUSHPLUS_TOKEN 或 SERVERCHAN_SENDKEY）')
    parser.add_argument('--pushplus', type=str, default=None, nargs='?',
                       const='FROM_ENV',
                       help='PushPlus Token（不传参则读 PUSHPLUS_TOKEN 环境变量）')
    parser.add_argument('--serverchan', type=str, default=None, nargs='?',
                       const='FROM_ENV',
                       help='Server酱 SendKey（不传参则读 SERVERCHAN_SENDKEY 环境变量）')
    parser.add_argument('--no-save', action='store_true',
                       help='不保存 Markdown 文件')
    parser.add_argument('--no-translate', action='store_true',
                       help='不翻译为中文，保持英文原文')
    args = parser.parse_args()

    do_translate = not args.no_translate

    # ====== 获取数据 ======
    print("🚀 正在获取 GitHub Trending 数据...")
    html = fetch_trending()
    if not html:
        sys.exit(1)

    print("📦 解析页面...")
    repos = parse_repos(html)
    if not repos:
        print("❌ 未解析到任何仓库，可能是页面结构已更新")
        sys.exit(1)

    print(f"✅ 共发现 {len(repos)} 个热门仓库")
    print("🔍 筛选 AI 相关项目...\n")

    ai_repos = [r for r in repos if is_ai_related(r)]

    # ====== 终端报告 ======
    print(format_console_report(ai_repos, len(repos)))

    # ====== 保存文件（含中文翻译） ======
    if not args.no_save:
        print("🌐 正在翻译描述为中文...")
        md_file = save_markdown(ai_repos, len(repos))
        print(f"📄 报告已保存: {md_file}")

    # ====== 微信推送 ======
    today_title = f"🤖 GitHub AI 日报 {datetime.now(timezone.utc).strftime('%m-%d')}"
    
    if do_translate:
        print("🌐 正在翻译推送内容...")
    push_md = build_push_markdown(ai_repos, len(repos), translate=do_translate)

    pushed = False

    if args.pushplus:
        token = os.environ.get("PUSHPLUS_TOKEN") if args.pushplus == 'FROM_ENV' else args.pushplus
        if not token or token == 'FROM_ENV':
            token = os.environ.get("PUSHPLUS_TOKEN")
        if token:
            pushed = push_pushplus(today_title, push_md, token)
        else:
            print("⚠️  使用 --pushplus 但未提供 Token")

    elif args.serverchan:
        key = os.environ.get("SERVERCHAN_SENDKEY") if args.serverchan == 'FROM_ENV' else args.serverchan
        if not key or key == 'FROM_ENV':
            key = os.environ.get("SERVERCHAN_SENDKEY")
        if key:
            pushed = push_serverchan(today_title, push_md, key)
        else:
            print("⚠️  使用 --serverchan 但未提供 SendKey")

    elif args.push:
        pp_token = os.environ.get("PUSHPLUS_TOKEN")
        sc_key = os.environ.get("SERVERCHAN_SENDKEY")
        if pp_token:
            pushed = push_pushplus(today_title, push_md, pp_token)
        elif sc_key:
            pushed = push_serverchan(today_title, push_md, sc_key)
        else:
            print("⚠️  使用 --push 但未设置 PUSHPLUS_TOKEN 或 SERVERCHAN_SENDKEY")

    # ====== 使用提示 ======
    print("\n" + "─" * 50)
    print("💡 推送微信:")
    print(f"   python {os.path.basename(sys.argv[0])} --pushplus 你的Token")
    print(f"   或设置环境变量 PUSHPLUS_TOKEN")
    print("─" * 50)


if __name__ == "__main__":
    main()
