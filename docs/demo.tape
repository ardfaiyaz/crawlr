# VHS tape to record the Crawlr demo GIF.
# Install VHS (https://github.com/charmbracelet/vhs), then run:
#   vhs docs/demo.tape
# Produces docs/demo.gif — reference it in the README and website hero.

Output docs/demo.gif

Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 24
Set Theme "Github Light"

Type "pip install crawlr"
Enter
Sleep 1s

Type "crawlr watch 'https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html' --target 60"
Enter
Sleep 2s

Type "crawlr watchlist"
Enter
Sleep 3s

Type "crawlr doctor"
Enter
Sleep 3s
