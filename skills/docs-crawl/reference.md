# Common Documentation & Wiki HTML Patterns

## Page Content

- Main content area: `<main>`, `<article>`, `.content`, `.markdown-body`, `#content`.
- Docusaurus: `.theme-doc-markdown`, `.markdown`.
- ReadTheDocs: `.rst-content`, `.document`.
- GitBook: `.page-inner`, `.page-body`.

## Headings & Hierarchy

- Standard `<h1>` through `<h6>` elements.
- Anchor links: `<a class="anchor" id="section-name">` or `<h2 id="section-name">`.
- Table of contents: `.toc`, `.table-of-contents`, `nav.toc`.

## Code Blocks

- `<pre><code class="language-python">` — language in class name.
- `<div class="highlight"><pre>` — Sphinx / Pygments style.
- `data-lang` attribute on `<code>` or `<pre>`.

## Sidebar Navigation

- `<nav class="sidebar">`, `.docs-sidebar`, `.menu`, `aside`.
- Nested `<ul>` / `<li>` with `<a>` links.

## Pagination / Next-Prev

- `.pagination-nav`, `.prev-next`, `a[rel="next"]`, `a[rel="prev"]`.
