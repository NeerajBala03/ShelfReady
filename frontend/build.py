"""
Build the standalone interactive demo: inject data/demo_data.json into the HTML
template so the result opens offline with zero setup (file:// friendly — no fetch).

Run:  python frontend/build.py
Out:  frontend/shelfready-demo.html
"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "demo_data.json")
TPL = os.path.join(HERE, "app_template.html")
OUT = os.path.join(HERE, "shelfready-demo.html")

OUT_STANDALONE = os.path.join(HERE, "shelfready-demo-standalone.html")

def build():
    data = open(DATA, encoding="utf-8").read()
    # guard against </script> inside JSON terminating the tag
    data = data.replace("</", "<\\/")
    html = open(TPL, encoding="utf-8").read().replace("__DEMO_DATA__", data)
    # Skeleton form (for publishing as an Artifact, which adds the doc wrapper).
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"Wrote {os.path.relpath(OUT)}  ({len(html)/1024:.0f} KB)  [artifact form]")

    # Standalone form (double-click / file://): add a full document wrapper.
    head, _, body = html.partition("</style>")
    standalone = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
                  '<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                  '<style>img{max-width:100%}[hidden]{display:none!important}'
                  'html,body{margin:0}</style>\n'
                  + head + "</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>")
    open(OUT_STANDALONE, "w", encoding="utf-8").write(standalone)
    print(f"Wrote {os.path.relpath(OUT_STANDALONE)}  ({len(standalone)/1024:.0f} KB)  [standalone]")

if __name__ == "__main__":
    build()
