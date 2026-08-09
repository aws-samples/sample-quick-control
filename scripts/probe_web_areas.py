#!/usr/bin/env python3
"""probe_web_areas.py — 逐个导航网页版 11 个功能区,dump 每区可操作元素,产出 skill 缺口清单。
纯读:只导航(改 location.href)+ 扫 DOM,不点任何创建/删除/提交按钮。
用法: uv run python probe_web_areas.py  → 结果写 /tmp/quickweb_areas.json + 打印摘要
环境变量: QUICK_WEB_REGION / QUICK_WEB_ACCOUNT / QUICK_WEB_BASE(整体覆盖前缀)
"""
import subprocess, json, time, sys, os

def _out_dir() -> str:
    """默认输出目录:用户私有缓存目录(0700),而不是全局可写的 /tmp。

    ★ 为什么不用 /tmp(bandit B108,PCSR 审核项):/tmp 全局可写且路径可预测,
      多用户机器上他人可预先创建同名文件或符号链接抢占(symlink attack),
      导致我们把截图/页面结构写到攻击者能读的位置、或覆盖其它文件。
      本项目是公开 sample —— 客户会照抄这个模式,所以这里做对更重要。
    覆盖方式:环境变量 QUICK_OUT_DIR,或命令行显式传路径(接口未变)。
    """
    d = os.environ.get("QUICK_OUT_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "quick-control")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _out(name: str) -> str:
    """把一个默认文件名解析成用户私有目录下的绝对路径。"""
    return os.path.join(_out_dir(), name)


AREAS = ["mystuff","spaces","research","agents","apps","flows",
         "analyses","dashboards","data","folders/personal","folders/shared"]
# 账户名因人/因组织而异,默认只给占位符 —— 跑之前先 export QUICK_WEB_ACCOUNT=...
BASE = os.environ.get(
    "QUICK_WEB_BASE",
    "https://{}.quicksight.aws.amazon.com/sn/account/{}/start/".format(
        os.environ.get("QUICK_WEB_REGION", "us-east-1"),
        os.environ.get("QUICK_WEB_ACCOUNT", "your-quick-account"),
    ),
).rstrip("/") + "/"

def osa(script):
    p = subprocess.run(["osascript","-e",script], capture_output=True, text=True)
    if p.returncode != 0:
        return "ERR:" + p.stderr.strip()
    return p.stdout.strip()

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

def eval_js(js):
    script = f'tell application "Google Chrome"{FIND}\n  return execute qsTab javascript {_as(js)}\nend tell'
    return osa(script)

# 扫当前区的可操作元素 + 主内容标题（ES5）
SCAN = r"""(function(){
var out={url:location.href.split('/start/')[1]||location.href, h1:'', tabs:[], actions:[], rows:0};
var h=document.querySelector('h1');if(h)out.h1=h.innerText.slice(0,30);
var bs=document.querySelectorAll('button,[role=button],[role=tab],a[href]');
var seen={};
for(var i=0;i<bs.length;i++){var e=bs[i];var r=e.getBoundingClientRect();
if(r.width>0&&r.height>0){var t=(e.getAttribute('aria-label')||e.innerText||'').replace(/\s+/g,' ').trim();
if(t&&t.length<30&&!seen[t]){seen[t]=1;
// 粗分:含"创建/新建/新增/create/add/发布/共享/删除"的算 action
if(/创建|新建|新增|添加|发布|共享|删除|重命名|移动|复制|导出|设置权限|create|new|add|publish|share|delete/i.test(t)){out.actions.push(t);}
else if(e.getAttribute('role')==='tab'){out.tabs.push(t);}
}}}
// 列表行数(粗估资产数量)
out.rows=document.querySelectorAll('[role=row],tr,[data-testid*=item],[class*=card]').length;
return JSON.stringify(out);
})()"""

def main():
    results = []
    for area in AREAS:
        url = BASE + area
        # 导航:直接改 location（比点按钮稳）
        eval_js("location.href=" + json.dumps(url))
        time.sleep(3.5)  # 等 SPA 路由+渲染  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        raw = eval_js(SCAN)
        try:
            d = json.loads(raw)
        except Exception:
            d = {"url": area, "raw_err": raw[:120]}
        results.append({"area": area, **d})
        acts = d.get("actions", [])
        print(f"[{area:18}] h1={d.get('h1','?'):12} 行~{d.get('rows','?'):>4}  动作: {', '.join(acts[:8]) if acts else '(无明显创建/管理按钮)'}")
    json.dump(results, open(_out("quickweb_areas.json"),"w"), ensure_ascii=False, indent=1)
    print("\n→ 详细 dump: /tmp/quickweb_areas.json")
    # 导航回 apps（恢复原样）
    eval_js("location.href=" + json.dumps(BASE + "apps"))

if __name__ == "__main__":
    main()
