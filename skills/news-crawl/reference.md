# Common News & Article HTML Patterns

## Article Containers

- `<article>` semantic element is the most reliable wrapper.
- Fallbacks: `div.article`, `div.post`, `div.story`, `div.entry`.

## Headlines

- `<h1>` inside `<article>` or `.article-title`, `.entry-title`, `.post-title`.
- `meta[property="og:title"]` as a reliable fallback.

## Author

- `<a rel="author">`, `.author`, `.byline`, `meta[name="author"]`.
- Sometimes nested: `<span class="byline"><a>Author Name</a></span>`.

## Publish Date

- `<time datetime="...">` is the most reliable source.
- `meta[property="article:published_time"]`.
- Class names: `.date`, `.published`, `.post-date`, `.timestamp`.

## Article Body

- `<div class="article-body">`, `.entry-content`, `.post-content`, `.story-body`.
- Strip ads, related-article blocks, and social share widgets from the body.

## Listing Pages

- Articles on index pages are typically in `<article>` or `<div class="post">` repeating blocks.
- Each block usually contains a link (`<a>`) to the full article page.
