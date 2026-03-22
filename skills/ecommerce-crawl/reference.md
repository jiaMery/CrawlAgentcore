# Common E-Commerce HTML Patterns

## Product Listings

Most e-commerce sites wrap products in repeating container elements:

- `<div class="product">` or `<article class="product-card">`
- `<li>` inside a `<ul class="products">` or `<ol class="product-list">`

## Price Selectors

- `.price`, `.product-price`, `[data-price]`
- Often nested: `<span class="price"><span class="currency">£</span>51.77</span>`
- Watch for sale prices vs original prices (`.price--sale`, `.price--original`)

## Pagination

- `<ul class="pagination">` with `<a>` links
- "Next" button: `.next a`, `a[rel="next"]`
- Page numbers: `.page-number`, `.pagination li a`

## Image URLs

- Product images often use lazy loading: check `data-src`, `data-lazy`, `srcset`
- Thumbnail vs full-size: prefer `data-full` or largest `srcset` entry
