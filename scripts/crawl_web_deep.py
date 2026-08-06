#!/usr/bin/env python3
"""crawl_web_deep.py — 深度串行采集网页版 11 区【所有】可操作元素,为 workflow 分析备料。
串行(单标签铁律):逐区导航→等渲染→全量扫元素(按钮/链接/tab/menuitem/输入框/行操作)→写文件。
纯读:不点创建/删除/提交。每区一个 json,汇总一个 index。
用法: uv run python crawl_web_deep.py [区名...]  (不传=全部11区)
环境变量: QUICK_WEB_REGION / QUICK_WEB_ACCOUNT / QUICK_WEB_BASE(整体覆盖前缀)
"""
import subprocess, json, time, sys, os

# 账户名因人/因组织而异,默认只给占位符 —— 跑之前先 export QUICK_WEB_ACCOUNT=...
BASE = os.environ.get(
    "QUICK_WEB_BASE",
    "https://{}.quicksight.aws.amazon.com/sn/account/{}/start/".format(
        os.environ.get("QUICK_WEB_REGION", "us-east-1"),
        os.environ.get("QUICK_WEB_ACCOUNT", "your-quick-account"),
    ),
).rstrip("/") + "/"
AREAS = ["mystuff","spaces","research","agents","apps","flows",
         "analyses","dashboards","data","folders/personal","folders/shared"]
OUT = "/tmp/quickweb_deep"

def osa(script):
    p = subprocess.run(["osascript","-e",script], capture_output=True, text=True)
    return "ERR:"+p.stderr.strip() if p.returncode else p.stdout.strip()

def _as(s): return '"' + s.replace("\\","\\\\").replace('"','\\"') + '"'

FIND = '''
  set qsTab to missing value
  repeat with w from 1 to count of windows
    repeat with t from 1 to count of tabs of window w
      if (URL of tab t of window w) contains "quicksight.aws.amazon.com" then
        set qsTab to tab t of window w
        exit repeat
      end if
    end repeat
    if qsTab is not missing value then exit repeat
  end repeat
  if qsTab is missing value then return "NOTAB"'''

def ejs(js):
    return osa(f'tell application "Google Chrome"{FIND}\n  return execute qsTab javascript {_as(js)}\nend tell')

# 全量扫描:分类抓 所有 可交互元素 + 主内容文本样本(ES5,无箭头/spread)
SCAN = r"""(function(){
function vis(e){var r=e.getBoundingClientRect();var s=getComputedStyle(e);
return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}
function lab(e){return (e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.getAttribute('title')||e.innerText||'').replace(/\s+/g,' ').trim().slice(0,40);}
var res={url:location.href, h1:'', buttons:[], links:[], tabs:[], menuitems:[], inputs:[], headings:[], sampleText:''};
var h=document.querySelector('h1');if(h)res.h1=h.innerText.slice(0,40);
var seen={};
function push(arr,e){var t=lab(e);if(t&&!seen[arr.__k+t]){seen[arr.__k+t]=1;arr.push(t);}}
res.buttons.__k='b';res.links.__k='l';res.tabs.__k='t';res.menuitems.__k='m';res.inputs.__k='i';
var all=document.querySelectorAll('button,[role=button],a[href],[role=tab],[role=menuitem],[role=menuitemcheckbox],input,textarea,[contenteditable=true],select');
for(var i=0;i<all.length;i++){var e=all[i];if(!vis(e))continue;
var role=e.getAttribute('role');var tag=e.tagName.toLowerCase();
if(role==='tab')push(res.tabs,e);
else if(role==='menuitem'||role==='menuitemcheckbox')push(res.menuitems,e);
else if(tag==='input'||tag==='textarea'||tag==='select'||e.isContentEditable)push(res.inputs,e);
else if(tag==='a')push(res.links,e);
else push(res.buttons,e);}
var hs=document.querySelectorAll('h2,h3,[role=heading]');var hh=[];
for(var j=0;j<hs.length&&hh.length<12;j++){var tt=hs[j].innerText.replace(/\s+/g,' ').trim();if(tt)hh.push(tt.slice(0,40));}
res.headings=hh;
var main=document.querySelector('main')||document.body;
res.sampleText=main.innerText.replace(/\n{2,}/g,' | ').slice(0,600);
delete res.buttons.__k;delete res.links.__k;delete res.tabs.__k;delete res.menuitems.__k;delete res.inputs.__k;
return JSON.stringify(res);
})()"""

def main():
    os.makedirs(OUT, exist_ok=True)
    areas = sys.argv[1:] or AREAS
    index = []
    for area in areas:
        ejs("location.href=" + json.dumps(BASE + area))
        time.sleep(4)  # SPA 路由 + 数据加载
        raw = ejs(SCAN)
        try: d = json.loads(raw)
        except Exception: d = {"area": area, "err": raw[:150]}
        fn = OUT + "/" + area.replace("/","_") + ".json"
        json.dump(d, open(fn,"w"), ensure_ascii=False, indent=1)
        nb=len(d.get("buttons",[]));nl=len(d.get("links",[]));ni=len(d.get("inputs",[]));nt=len(d.get("tabs",[]))
        index.append({"area":area,"h1":d.get("h1",""),"buttons":nb,"links":nl,"inputs":ni,"tabs":nt,"file":fn})
        print(f"[{area:16}] h1={d.get('h1','?'):10} btn={nb:>3} link={nl:>3} tab={nt:>2} input={ni:>2}")
    json.dump(index, open(OUT+"/_index.json","w"), ensure_ascii=False, indent=1)
    ejs("location.href=" + json.dumps(BASE + "apps"))  # 恢复
    print(f"\n→ 逐区 dump 在 {OUT}/*.json，索引 {OUT}/_index.json")

if __name__ == "__main__":
    main()
