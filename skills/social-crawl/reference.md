# Common Social Media & Forum HTML Patterns

## Post Containers

- `<article>`, `<div class="post">`, `<div class="tweet">`, `<div class="comment">`.
- Reddit-style: `.thing`, `.Post`, `[data-testid="post-container"]`.
- Forum threads: `.message`, `.post-body`, `.forum-post`.

## Author / Username

- `.author`, `.username`, `[data-author]`, `a[href*="/user/"]`.
- Display name vs handle: often separate elements.

## Timestamps

- `<time datetime="...">` is the most reliable.
- `[data-timestamp]`, `.timestamp`, `.post-date`.
- Relative times ("2h ago") may need conversion.

## Post Content

- `.post-content`, `.post-text`, `.message-body`, `.comment-body`.
- May contain embedded media, links, and mentions.

## Engagement Metrics

- `.score`, `.likes`, `.upvotes`, `.reactions`, `[data-score]`.
- Comment / reply counts: `.comment-count`, `.reply-count`.

## Threads & Replies

- Nested `<div>` or `<ul>` structures for reply chains.
- `data-parent-id` or `data-depth` attributes for threading.
