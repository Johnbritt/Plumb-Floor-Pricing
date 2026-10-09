import json,re
from paths import RESULTS, DEMO, p as P_
r=json.load(open(P_(RESULTS,"results_v2.json")))["world2_confirmation"]
arms={k:{"label":re.sub(r"^[A-Z]\.\s*","",v["label"]),**{x:v[x] for x in("capture","capture_ci","refuse_rate","harmful_move_rate","capture_thin")}} for k,v in r["arms"].items()}
res=dict(arms=arms,diffs=r["diffs"],n_decisions=r["n_decisions"],n_anomaly=r["n_anomaly_decisions"],sensitivity=r["sensitivity"],harm_multiplier=r["harm_multiplier"],refusal_agent=r["refusal_agent"])
days=json.load(open(P_(DEMO,"demo_queue.json")))
pil={k:json.load(open(P_(RESULTS,f"pilot_{k}.json"))) for k in ["as_written","four_weeks","forty_cells"]}
import os
t=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"product_template.html")).read()
frag=t.replace("/*DAYS*/",json.dumps(days,separators=(",",":"))).replace("/*RESULTS*/",json.dumps(res,separators=(",",":"))).replace("/*PILOT*/",json.dumps(pil,separators=(",",":")))
open(P_(DEMO,"plumb_product_fragment.html"),"w").write(frag)
full=('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style></head><body>'+frag+"</body></html>")
m=re.search(r"<title>.*?</title>",full); ti=m.group(0); full=full.replace(ti,"",1).replace("</head>",ti+"</head>",1)
open(P_(DEMO,"index.html"),"w").write(full)   # static hosts (Vercel, Netlify, GitHub Pages) serve this
print(len(frag))
