"""首页 Feed 列表，对应 Go xiaohongshu/feeds.go。"""

from __future__ import annotations

import json
import logging
import time

from .cdp import Page
from .errors import NoFeedsError
from .types import Feed
from .urls import EXPLORE_URL, HOME_URL

logger = logging.getLogger(__name__)

# 从 __INITIAL_STATE__ 提取 feeds 的 JS
_EXTRACT_FEEDS_JS = """
(() => {
    if (window.__INITIAL_STATE__ &&
        window.__INITIAL_STATE__.feed &&
        window.__INITIAL_STATE__.feed.feeds) {
        const feeds = window.__INITIAL_STATE__.feed.feeds;
        const feedsData = feeds.value !== undefined ? feeds.value : feeds._value;
        if (feedsData) {
            return JSON.stringify(feedsData);
        }
    }
    return "";
})()
"""


def list_feeds(page: Page, skip_navigate: bool = False) -> list[Feed]:
    """获取首页 Feed 列表。

    Args:
        page: CDP 页面对象。
        skip_navigate: 若当前页面已是 explore/home 则不导航。

    Raises:
        NoFeedsError: 没有捕获到 feeds 数据。
    """
    navigated = True
    
    if skip_navigate:
        current_url = (page.evaluate("location.href") or "").strip()
        #print(current_url)
        if current_url.startswith(EXPLORE_URL) or current_url.startswith(HOME_URL):
            logger.info("当前已在 explore/home 页面，跳过导航: %s", current_url)
            navigated = False
    #return []
    if navigated:
        page.navigate(HOME_URL)
        page.wait_for_load()
        page.wait_dom_stable()
        time.sleep(1)

    result = page.evaluate(_EXTRACT_FEEDS_JS)
    if not result:
        raise NoFeedsError()

    feeds_data = json.loads(result)
    return [Feed.from_dict(f) for f in feeds_data]
