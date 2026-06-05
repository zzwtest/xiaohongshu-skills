"""搜索关键词 → 打开第一条 Feed → 获取最新 N 条评论 → AI 推荐评论。

用法:
    python scripts/search_and_comment.py <关键词> [评论数] [--ai-recommend]
    --navigate   使用导航方式打开详情页（非弹层）
    --index N    点击第几条笔记（默认 0）
"""

from __future__ import annotations

import json
import sys
import time

# 让 xhs 包可导入
_parent = __file__ and __import__("pathlib").Path(__file__).resolve().parent
if _parent and str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

import requests
from xhs.bridge import BridgePage
from xhs.comment import post_comment
from xhs.feed_detail import get_feed_detail, get_feed_detail_by_current
from xhs.search import search_feeds
from xhs.types import CommentLoadConfig, FilterOption

# AI API 配置
_AI_API_URL = "http://10.255.216.25:15721/v1/chat/completions"
_AI_API_KEY = "Bearer 4853be22-2230-43df-8227-6d67f6207504"
_AI_MODEL = "qwen3.7-plus"


def _ensure_bridge() -> BridgePage:
    """确保 bridge 就绪，返回 BridgePage。"""
    from xhs.bridge import BridgePage as BP

    page = BP()
    if not page.is_server_running():
        print("请先启动 bridge_server.py", file=sys.stderr)
        sys.exit(1)

    if not page.is_extension_connected():
        print("浏览器扩展未连接，请确认 XHS Bridge 扩展已安装并启用", file=sys.stderr)
        sys.exit(1)

    return BP()


def _call_ai(title: str, desc: str, cover_url: str, comments: list[dict]) -> dict:
    """调用 AI 模型生成推荐评论。"""
    # 取最新 10 条评论作为上下文
    recent = comments[:10]
    comment_texts = "\n".join(
        f"  - [{c.get('user', {}).get('nickname', '匿名')}]: {c.get('content', '')}"
        for c in recent
    )

    prompt = f"""你是一个小红书用户，正在浏览一篇笔记。请根据笔记内容和已有评论，写一条自然、有价值的评论。

【笔记标题】{title}
【笔记正文】{desc[:300]}
【封面图】{cover_url}
【近期评论】
{comment_texts if comment_texts else '（暂无评论）'}

要求：
- 评论可以结合封面图片内容，体现出你看懂了图
- 语言自然接地气，像真人写的，不要 AI 腔
- 5-30 字
- 不要 emoji 堆砌
- 只输出评论内容，不要引号、不要"评论："前缀"""
    print(prompt)
    resp = requests.post(
        _AI_API_URL,
        headers={
            "Authorization": _AI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": _AI_MODEL,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    return {"recommendedComment": content, "raw": data}


def main() -> None:
    args = sys.argv[1:]
    ai_recommend = "--ai-recommend" in args
    use_navigate = "--navigate" in args
    feed_index = 0
    tmp_args = list(args)
    if "--index" in tmp_args:
        idx_pos = tmp_args.index("--index")
        if idx_pos + 1 < len(tmp_args):
            feed_index = int(tmp_args[idx_pos + 1])
    pos_args = [a for a in args if not a.startswith("--") and a not in ("--index", str(feed_index))]

    keyword = pos_args[0] if pos_args else input("请输入搜索关键词: ").strip()
    if not keyword:
        print("关键词不能为空", file=sys.stderr)
        sys.exit(2)

    max_comments = int(pos_args[1]) if len(pos_args) > 1 else 30

    page = _ensure_bridge()

    try:
        # 1. 搜索关键词，按最多评论 + 一天内排序
        #print(f'搜索: "{keyword}" (最多评论 + 一天内) ...')
        filter_opt = FilterOption(sort_by="最多评论", publish_time="一周内")
        feeds = search_feeds(page, keyword, filter_opt)

        if not feeds:
            print("没有搜索结果", file=sys.stderr)
            sys.exit(2)

        print(f"找到 {len(feeds)} 条结果，等待 3 秒后打开 ...")
        time.sleep(3)

        # 2. 打开 Feed，获取最新 N 条评论
        first = feeds[feed_index] if feed_index < len(feeds) else feeds[0]
        cover_url = first.note_card.cover.url_default or first.note_card.cover.url or ""
        print(f'  Feed: {first.note_card.display_title}')
        print(f'  Feed ID: {first.id}')
        print(f'  Cover: {cover_url}')

        config = CommentLoadConfig(max_comment_items=max_comments)
        if use_navigate:
            detail = get_feed_detail(
                page,
                first.id,
                first.xsec_token,
                load_all_comments=True,
                config=config,
                keyword=keyword,
            )
        else:
            print(f"  点击第 {feed_index + 1} 条链接（弹层模式）...")
            detail = get_feed_detail_by_current(
                page,
                index=feed_index,
                load_all_comments=True,
                config=config,
            )

        # 3. 组装输出
        comments_list = [c.to_dict() for c in detail.comments.list_]
        output = {
            "keyword": keyword,
            "feed": {
                "id": detail.note.note_id,
                "title": detail.note.title,
                "desc": detail.note.desc,
                "type": detail.note.type,
                "time": detail.note.time,
                "ipLocation": detail.note.ip_location,
                "cover": cover_url,
                "user": {
                    "userId": detail.note.user.user_id,
                    "nickname": detail.note.user.nickname,
                },
                "interactInfo": {
                    "likedCount": detail.note.interact_info.liked_count,
                    "collectedCount": detail.note.interact_info.collected_count,
                    "commentCount": detail.note.interact_info.comment_count,
                    "sharedCount": detail.note.interact_info.shared_count,
                },
            },
            "comments": comments_list,
            "commentCount": len(comments_list),
        }

        # 4. AI 推荐评论 + 确认后自动评论
        if ai_recommend:
            print("AI 生成推荐评论中 ...", file=sys.stderr)
            try:
                ai_result = _call_ai(
                    detail.note.title,
                    detail.note.desc,
                    cover_url,
                    comments_list,
                )
                recommended = ai_result["recommendedComment"]
                output["aiRecommend"] = recommended

                print(f"\n{'='*50}", file=sys.stderr)
                print(f"AI 推荐评论:\n  {recommended}", file=sys.stderr)
                print(f"{'='*50}", file=sys.stderr)

                choice = input("\n是否自动发表这条评论？(y/n): ").strip().lower()
                if choice in ("y", "yes"):
                    print("正在发表评论 ...", file=sys.stderr)
                    post_comment(
                        page,
                        detail.note.note_id,
                        first.xsec_token,
                        recommended,
                        skip_navigate=not use_navigate,
                    )
                    output["posted"] = True
                    output["postedContent"] = recommended
                    print("评论已发表", file=sys.stderr)
                else:
                    output["posted"] = False
                    print("跳过评论", file=sys.stderr)
            except Exception as e:
                output["aiRecommendError"] = str(e)

        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(2)


if __name__ == "__main__":
    main()
