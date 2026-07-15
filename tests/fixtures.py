"""HTML fixtures used by the offline test suite.

Two versions of a product listing page with DIFFERENT markup (v1 uses semantic
microdata + `.product` cards; v2 renames classes to simulate a site redesign).
This lets us verify (a) extraction works and (b) the engine self-heals when the
cached selectors break after a layout change.
"""

# v1: schema.org microdata, .product cards
LISTING_V1 = """
<!doctype html><html><body>
<main>
  <ul class="results">
    <li class="product" itemtype="http://schema.org/Product">
      <a class="product-link" href="/p/1"><img class="product-image" src="/img/1.jpg"></a>
      <h2 class="product-title"><a href="/p/1">Wireless Mouse</a></h2>
      <span class="price" itemprop="price">24.99</span>
    </li>
    <li class="product" itemtype="http://schema.org/Product">
      <a class="product-link" href="/p/2"><img class="product-image" src="/img/2.jpg"></a>
      <h2 class="product-title"><a href="/p/2">Mechanical Keyboard</a></h2>
      <span class="price" itemprop="price">79.00</span>
    </li>
  </ul>
</main>
</body></html>
"""

# v2: same data, redesigned markup (renamed container/classes) + a price change.
# Mouse price dropped 24.99 -> 19.99; keyboard unchanged.
LISTING_V2 = """
<!doctype html><html><body>
<main>
  <div class="grid">
    <article class="card" itemtype="http://schema.org/Product">
      <a href="/p/1"><img itemprop="image" src="/img/1.jpg"></a>
      <h3 class="name"><a href="/p/1">Wireless Mouse</a></h3>
      <div class="cost" itemprop="price">19.99</div>
    </article>
    <article class="card" itemtype="http://schema.org/Product">
      <a href="/p/2"><img itemprop="image" src="/img/2.jpg"></a>
      <h3 class="name"><a href="/p/2">Mechanical Keyboard</a></h3>
      <div class="cost" itemprop="price">79.00</div>
    </article>
  </div>
</main>
</body></html>
"""

PRODUCT_PAGE = """
<!doctype html><html><body>
<div itemtype="http://schema.org/Product">
  <h1 class="product-title">4K Monitor 27"</h1>
  <span class="price" itemprop="price">299.50</span>
  <div class="availability">In Stock</div>
  <span class="rating">4.6</span>
  <img class="product-image" src="/img/monitor.jpg">
</div>
</body></html>
"""
