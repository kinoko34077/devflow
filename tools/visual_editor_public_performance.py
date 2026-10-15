#!/usr/bin/env python3
"""Bounded public browser measurements for the opt-in editor; no mutation or stress traffic."""
import json
import os
from statistics import median
from time import monotonic
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

SITES = [
  {"name": "frequency-warp", "url": "https://kinoko34077.github.io/frequency-warp-vst/",
   "query": "visual_editor_v2=1", "ready": "dom"},
  {"name": "line-style-viewer", "url": "https://kinoko34077.github.io/line-style-viewer/",
   "query": "visual_editor_v2=1", "ready": "dom"},
]
if os.environ.get("INCLUDE_GOMOKU") == "1":
  SITES.append({"name": "Gomoku-5D", "url": "https://kinoko34077.github.io/Gomoku-5D/",
                "query": "visual_editor_model=1", "ready": "model"})

RUNS = 3
WIDTHS = (390, 1280)
def snap(page):
    return page.evaluate("""() => {
      const nav=performance.getEntriesByType('navigation')[0] || {};
      const assets=performance.getEntriesByType('resource');
      const paint=performance.getEntriesByType('paint');
      const fcp=paint.find(x=>x.name==='first-contentful-paint');
      const sum=(list,key)=>list.reduce((s,v)=>s+(v[key]||0),0);
      return {
        domMs:Math.round(nav.domContentLoadedEventEnd||0),
        loadMs:Math.round(nav.loadEventEnd||0),
        firstPaintMs:fcp?Math.round(fcp.startTime):null,
        requests:assets.length,
        transferKB:Math.round(sum(assets,'transferSize')/1024),
        decodedKB:Math.round(sum(assets,'decodedBodySize')/1024),
        jsDecodedKB:Math.round(sum(assets.filter(x=>/\\.m?js(?:[?#]|$)/.test(x.name)),'decodedBodySize')/1024)
      };
    }""")

def run():
  output=[]
  with sync_playwright() as p:
    browser=p.chromium.launch(executable_path="/usr/bin/google-chrome",
                              args=["--no-sandbox","--disable-dev-shm-usage"])
    try:
      for site in SITES:
        for width in WIDTHS:
          for mode in ("normal","editor"):
            samples=[]
            for _ in range(RUNS):
              context=browser.new_context(viewport={"width":width,"height":844},
                                          reduced_motion="reduce",service_workers="block",
                                          accept_downloads=False)
              page=context.new_page()
              cdp=context.new_cdp_session(page)
              cdp.send("Performance.enable")
              failures=[]
              page.on("pageerror",lambda e: failures.append(str(e)))
              page.on("response",lambda r: failures.append("HTTP "+str(r.status)+" "+r.url)
                      if r.status >= 400 and urlsplit(r.url).hostname == urlsplit(site["url"]).hostname else None)
              url=site["url"]+("?" + site["query"] if mode=="editor" else "")
              start=monotonic()
              response=page.goto(url,wait_until="load",timeout=35000)
              if response is None or response.status!=200:
                raise AssertionError(site["name"]+" index not HTTP 200: "+str(response.status if response else None))
              if mode=="editor":
                if site["ready"]=="dom":
                  page.wait_for_function("""() => !!document.querySelector('#visual-editor-v2')
                    ?.shadowRoot?.querySelector('#exportcss')""",timeout=20000)
                else:
                  page.locator('[data-ve-model-pilot="1"] [data-action="export-layout"]').wait_for(timeout=20000)
              else:
                assert page.locator("#visual-editor-v2").count()==0
                assert page.locator('[data-ve-model-pilot="1"]').count()==0
              page.wait_for_timeout(120)
              record=snap(page)
              metrics={v["name"]:v["value"] for v in cdp.send("Performance.getMetrics")["metrics"]}
              record["heapKB"]=round(metrics.get("JSHeapUsedSize",0)/1024)
              record["taskMs"]=round(metrics.get("TaskDuration",0)*1000,1)
              record["scriptMs"]=round(metrics.get("ScriptDuration",0)*1000,1)
              record["layoutMs"]=round(metrics.get("LayoutDuration",0)*1000,1)
              record["readyMs"]=round((monotonic()-start)*1000)
              record["errors"]=failures
              samples.append(record)
              context.close()
            keys=["readyMs","domMs","loadMs","firstPaintMs","requests",
                  "transferKB","decodedKB","jsDecodedKB","heapKB","taskMs","scriptMs","layoutMs"]
            result={"site":site["name"],"width":width,"mode":mode,"samples":RUNS}
            for k in keys:
              nums=[s[k] for s in samples if s[k] is not None]
              result["median_"+k]=round(median(nums),1) if nums else None
            result["error_count"]=sum(len(s["errors"]) for s in samples)
            result["examples_of_errors"]=sorted(set(e for s in samples for e in s["errors"]))[:4]
            print("VISUAL_EDITOR_PUBLIC_PERF="+json.dumps(result,ensure_ascii=False),flush=True)
            output.append(result)
      for site in SITES:
        for width in WIDTHS:
          normal=next(x for x in output if x["site"]==site["name"] and x["width"]==width and x["mode"]=="normal")
          editor=next(x for x in output if x["site"]==site["name"] and x["width"]==width and x["mode"]=="editor")
          print("PERF_DELTA="+json.dumps({
             "site":site["name"],"width":width,
             "extraReadyMs":round(editor["median_readyMs"]-normal["median_readyMs"],1),
             "extraDecodedKB":round(editor["median_decodedKB"]-normal["median_decodedKB"],1),
             "extraHeapKB":round(editor["median_heapKB"]-normal["median_heapKB"],1),
             "extraTaskMs":round(editor["median_taskMs"]-normal["median_taskMs"],1)
          }),flush=True)
    finally:
      browser.close()
if __name__=="__main__":
  run()
