"""Render docs/CASE_STUDY.md to a styled PDF (same palette as the product demo)."""
import re, markdown, pathlib
from playwright.sync_api import sync_playwright
R = pathlib.Path(__file__).resolve().parent.parent
md = (R/"docs/CASE_STUDY.md").read_text()
md = md.replace("# PLUMB Case Study\n", "", 1)
lines = md.strip().split("\n")
tag = lines[0].strip("*"); rest = "\n".join(lines[1:])
by = [l for l in rest.split("\n") if l.startswith("By ")][0]
note = [l for l in rest.split("\n") if l.startswith("*All numbers")][0].strip("*")
rest = rest.replace(by, "").replace("*"+note+"*", "")
body = markdown.markdown(rest, extensions=["tables"])
body = body.replace("<h2>", "<h2><i></i>")
CSS = """
@page{size:A4;margin:16mm 16mm 18mm}
:root{--ink:#0b0b0c;--muted:#5d5d63;--line:#e4e4e1;--accent:#ff5b14;--accent-ink:#c93d00;--soft:#fff0e7;--bg:#f6f6f5}
*{box-sizing:border-box}
body{font:10.5pt/1.55 "Geist",Inter,system-ui,sans-serif;color:var(--ink);margin:0}
.cover{background:var(--ink);color:#fff;margin:-16mm -16mm 8mm;padding:16mm 16mm 12mm}
.brand{font-size:9pt;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:700}
.cover h1{font-size:34pt;line-height:1.05;margin:6mm 0 4mm;letter-spacing:-.02em}
.cover .tag{font-size:13.5pt;line-height:1.4;color:#e8e8e6;max-width:150mm}
.cover .by{margin-top:7mm;font-size:9.5pt;color:#b9b9b6}
.note{background:var(--soft);border-left:3px solid var(--accent);padding:3mm 4mm;font-size:9.5pt;color:#5a2a10;margin:0 0 6mm}
h2{font-size:15pt;margin:7mm 0 2.5mm;letter-spacing:-.01em;display:flex;align-items:center;gap:2.5mm;break-after:avoid}
h2 i{display:inline-block;width:3mm;height:3mm;background:var(--accent);border-radius:1px}
p{margin:0 0 2.5mm}
ul,ol{margin:0 0 3mm;padding-left:5mm}li{margin:0 0 1.6mm}
li::marker{color:var(--accent);font-weight:700}
strong{font-weight:700}
a{color:var(--accent-ink)}
code{font-family:"Geist Mono",ui-monospace,Menlo,monospace;font-size:9pt;background:var(--bg);padding:.2mm 1mm;border-radius:2px}
table{width:100%;border-collapse:collapse;margin:2mm 0 4mm;font-size:9.5pt;break-inside:avoid}
th{background:var(--ink);color:#fff;text-align:left;padding:2mm 2.5mm;font-weight:600}
td{padding:2mm 2.5mm;border-bottom:1px solid var(--line)}
td:not(:first-child),th:not(:first-child){font-variant-numeric:tabular-nums;white-space:nowrap}
tr:nth-child(even) td{background:#fafaf9}
"""
html = f"""<!doctype html><meta charset=utf-8><style>{CSS}</style>
<div class=cover><div class=brand>PLUMB &nbsp;·&nbsp; Case study</div><h1>Floor pricing,<br>with a human in charge</h1>
<div class=tag>{tag}</div><div class=by>{by[3:]}</div></div>
<div class=note>{note}</div>{body}"""
out = R/"docs/PLUMB_Case_Study.pdf"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
    pg.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True,
           header_template="<span></span>",
           footer_template='<div style="width:100%;font:8px sans-serif;color:#8c8c93;padding:0 16mm;display:flex;justify-content:space-between"><span>PLUMB case study</span><span>Page <span class=pageNumber></span> of <span class=totalPages></span></span></div>',
           margin={"top":"16mm","bottom":"18mm","left":"16mm","right":"16mm"})
    b.close()
print("ok")
