# -*- coding: utf-8 -*-
"""把彙整結果渲染成一份自包含的 HTML 儀表板（圖表用 ECharts CDN）。"""
from __future__ import annotations

import json
from typing import Dict, List

import config as cfg
from config import PILLAR_WEIGHTS

_LIGHT_LABEL = {"green": "偏多／加碼", "amber": "中性", "red": "偏空／保守", "gray": "無資料"}

# HTML 靜態骨架（不含 Python 變數，避免大括號轉義問題；資料以 JSON 注入）
_HEAD = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="refresh" content="__REFRESH__">
<title>市場進場儀表板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>window.echarts||document.write('<script src="https://unpkg.com/echarts@5.5.0/dist/echarts.min.js"><\\/script>');</script>
<style>
:root{
  --bg:#0e1116; --panel:#171b24; --panel2:#1e2430; --line:#2a3142;
  --text:#e7ebf3; --muted:#aab4c6; --green:#34d07f; --amber:#f9b43a; --red:#ef5d5d; --accent:#5b9cff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.5}
a{color:var(--accent)}
.wrap{max-width:1180px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:24px;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.hero{display:grid;grid-template-columns:300px 1fr;gap:20px;background:var(--panel);
  border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:22px}
@media(max-width:760px){.hero{grid-template-columns:1fr}}
#gauge{width:300px;height:230px;margin:auto}
.verdict{display:flex;flex-direction:column;justify-content:center}
.badge{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:15px;width:fit-content}
.verdict h2{font-size:30px;margin:6px 0}
.verdict p{color:var(--muted);margin:6px 0 14px}
.mult{font-size:15px}
.mult b{font-size:26px;color:var(--accent)}
.hist{height:60px;margin-top:14px}
.pillars{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:26px}
@media(max-width:860px){.pillars{grid-template-columns:repeat(2,1fr)}}
.pcard{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.pcard .pn{font-size:13px;color:var(--muted)}
.pcard .ps{font-size:26px;font-weight:700;margin:2px 0}
.pcard .pw{font-size:11px;color:var(--muted)}
.section-title{font-size:15px;font-weight:700;margin:26px 0 12px;padding-left:10px;border-left:3px solid var(--accent)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
  display:grid;grid-template-columns:1fr 150px;gap:10px 14px;align-items:center}
.card .top{grid-column:1/3;display:flex;align-items:center;gap:8px}
.dot{width:10px;height:10px;border-radius:50%;flex:none}
.name{font-weight:600;font-size:15px}
.val{font-size:13px;color:var(--muted);margin-top:2px}
.barwrap{grid-column:1/2}
.bar{height:8px;background:var(--panel2);border-radius:6px;overflow:hidden}
.bar > i{display:block;height:100%;border-radius:6px}
.scoretxt{font-size:12px;color:var(--muted);margin-top:4px}
.spark{grid-column:2/3;grid-row:2/4;width:150px;height:54px}
.note{grid-column:1/3;font-size:12.5px;color:var(--muted)}
.detail{grid-column:1/3;font-size:12px;color:var(--accent);opacity:.9}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
.warn{background:rgba(234,84,85,.12);border:1px solid rgba(234,84,85,.4);color:#ffb3b3;
  padding:8px 12px;border-radius:8px;font-size:12.5px;margin-bottom:16px}
.legend{font-size:12px;color:var(--muted);margin-top:6px}
.legend span{margin-right:14px}
.navbar{position:sticky;top:0;z-index:50;background:rgba(11,14,19,.92);backdrop-filter:blur(6px);
  border-bottom:1px solid #222936}
.navbar .inner{max-width:1320px;margin:0 auto;padding:9px 16px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.navbar .brand{font-weight:800;color:#e7ebf3;text-decoration:none;margin-right:10px}
.navbar a.tab{text-decoration:none;padding:6px 13px;border-radius:8px;font-size:14px;color:#aeb8c8}
.navbar a.tab:hover{background:#1a2030}
.navbar a.tab.on{background:#1f6feb;color:#fff}
</style>
</head>
<body>
"""

_TAIL = """
</div>
<script>
const C={green:'#28c76f',amber:'#f6a821',red:'#ea5455',gray:'#6b7280'};
const fmt=v=>(v>0?'+':'')+v.toFixed(1);

// 綜合分數儀表
(function(){
  const el=document.getElementById('gauge'); if(!el)return;
  if(typeof echarts==='undefined'){el.innerHTML='<div style="padding:40px 10px;color:#aab4c6;font-size:13px;text-align:center">圖表元件載入失敗（離線或網路受阻），分數與文字不受影響。</div>';return;}
  const g=echarts.init(el,null,{renderer:'canvas'});
  g.setOption({series:[{type:'gauge',min:0,max:100,radius:'100%',center:['50%','62%'],
    startAngle:210,endAngle:-30,
    axisLine:{lineStyle:{width:16,color:[[0.35,C.red],[0.45,'#f6862a'],[0.58,C.amber],[0.70,'#7cc24a'],[1,C.green]]}},
    pointer:{width:5,length:'62%',itemStyle:{color:'#e7ebf3'}},
    axisTick:{show:false},splitLine:{length:14,lineStyle:{color:'#39414f'}},
    axisLabel:{color:'#8590a3',fontSize:10,distance:-30},
    progress:{show:false},
    detail:{valueAnimation:true,fontSize:40,fontWeight:'bold',offsetCenter:[0,'38%'],
      color:'#e7ebf3',formatter:'{value}'},
    title:{show:false},
    data:[{value:DASH.composite}]}]});
  window.addEventListener('resize',()=>g.resize());
})();

// 分數歷史
(function(){
  const el=document.getElementById('score-hist'); if(!el||!DASH.score_history||DASH.score_history.length<2)return;
  const h=echarts.init(el); const xs=DASH.score_history.map(d=>d[0]); const ys=DASH.score_history.map(d=>d[1]);
  h.setOption({grid:{left:4,right:4,top:6,bottom:4},xAxis:{type:'category',data:xs,show:false},
    yAxis:{type:'value',min:0,max:100,show:false},
    tooltip:{trigger:'axis',formatter:p=>p[0].axisValue+'：'+p[0].data},
    series:[{type:'line',data:ys,smooth:true,symbol:'none',lineStyle:{color:C.accent||'#5b9cff',width:2},
      areaStyle:{color:'rgba(91,156,255,.15)'}}]});
  window.addEventListener('resize',()=>h.resize());
})();

// 各指標走勢迷你圖
DASH.indicators.forEach(ind=>{
  if(!ind.series||ind.series.length<3)return;
  const el=document.getElementById('spark-'+ind.key); if(!el)return;
  const c=echarts.init(el); const col=C[ind.light]||C.gray;
  c.setOption({grid:{left:2,right:2,top:4,bottom:2},
    xAxis:{type:'category',show:false,data:ind.series.map((_,i)=>i)},
    yAxis:{type:'value',scale:true,show:false},
    tooltip:{trigger:'axis',formatter:p=>p[0].data},
    series:[{type:'line',data:ind.series,smooth:true,symbol:'none',
      lineStyle:{color:col,width:1.8},areaStyle:{color:col+'22'}}]});
  window.addEventListener('resize',()=>c.resize());
});
</script>
</body></html>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# PWA：加入主畫面變成 App（圖示、全螢幕、離線）。放進每頁 <head>。
_OG_DESC = ("幾十項指標 → 一個 0–100 進場分數。法人 vs 散戶背離、景氣循環、AI 噴發偵測、"
            "個股搜尋（上市＋上櫃）、推薦回測。每日自動更新・非投資建議。")
_OG_BASE = "https://%s.github.io/%s" % (getattr(cfg, "GITHUB_USER", "stocktracker-tw"),
                                        getattr(cfg, "GITHUB_REPO", "market-dashboard"))
PWA_HEAD = ('<link rel="manifest" href="manifest.webmanifest">'
            '<meta name="theme-color" content="#0f2148">'
            '<link rel="apple-touch-icon" href="apple-icon-v9.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            '<meta name="apple-mobile-web-app-title" content="Stock Tracker">'
            # SEO + 社群分享預覽（Threads/LINE/FB 連結會帶大圖）
            '<meta name="description" content="' + _OG_DESC + '">'
            '<meta property="og:site_name" content="Stock Tracker">'
            '<meta property="og:title" content="Stock Tracker — 進場時機儀表板">'
            '<meta property="og:description" content="' + _OG_DESC + '">'
            '<meta property="og:image" content="' + _OG_BASE + '/cover.png">'
            '<meta property="og:type" content="website">'
            '<meta name="twitter:card" content="summary_large_image">'
            '<meta name="twitter:title" content="Stock Tracker — 進場時機儀表板">'
            '<meta name="twitter:description" content="' + _OG_DESC + '">'
            '<meta name="twitter:image" content="' + _OG_BASE + '/cover.png">'
            '<script>if("serviceWorker" in navigator){addEventListener("load",function(){'
            'navigator.serviceWorker.register("sw.js").catch(function(){})})}</script>')


def with_pwa(html: str) -> str:
    """把 PWA 標籤插進 <head>。"""
    return html.replace("</head>", PWA_HEAD + "</head>", 1)


# 在分頁列上「按住 icon → 浮起的玻璃膠囊跟著手指滑動 → 放開在哪個 icon 就去那頁」。
# 純拖曳互動；放開後用 View Transitions 做方向感滑入（iOS Safari 不支援轉場則直接切頁）。
SWIPE_JS = """<script>
(function(){
 if(window.__tabdrag)return;window.__tabdrag=1;
 var order=["news.html","index.html","perspectives.html","stocks.html"];
 function curIdx(){var f=(location.pathname.split("/").pop()||"").toLowerCase();
  if(f==="news.html")return 0;if(f==="perspectives.html")return 2;if(f==="stocks.html")return 3;return 1;}
 function start(){
  var bar=document.querySelector(".tabbar");if(!bar)return;
  var tabs=[].slice.call(bar.querySelectorAll("a.tab"));if(tabs.length<2)return;
  bar.classList.add("js");
  var thumb=document.createElement("span");thumb.className="thumb";bar.insertBefore(thumb,bar.firstChild);
  var cur=curIdx(),over=cur,dragging=false;
  function hl(i){for(var k=0;k<tabs.length;k++)tabs[k].classList.toggle("hl",k===i);}
  function place(i,anim){var br=bar.getBoundingClientRect(),r=tabs[i].getBoundingClientRect();
   thumb.style.transition=anim?"":"none";
   thumb.style.width=r.width+"px";thumb.style.height=r.height+"px";
   thumb.style.top=(r.top-br.top)+"px";thumb.style.left=(r.left-br.left)+"px";}
  function nearest(x){var best=0,bd=1e9;for(var k=0;k<tabs.length;k++){
   var r=tabs[k].getBoundingClientRect(),c=r.left+r.width/2,d=Math.abs(x-c);
   if(d<bd){bd=d;best=k;}}return best;}
  function follow(x){var br=bar.getBoundingClientRect(),w=thumb.offsetWidth;
   var lo=tabs[0].getBoundingClientRect().left-br.left;
   var hi=tabs[tabs.length-1].getBoundingClientRect().left-br.left;
   var L=Math.max(lo,Math.min(hi,x-br.left-w/2));
   thumb.style.transition="none";thumb.style.left=L+"px";
   var o=nearest(x);if(o!==over){over=o;hl(o);}}
  requestAnimationFrame(function(){place(cur,false);hl(cur);});
  function down(x,e){dragging=true;over=nearest(x);bar.classList.add("dragging");
   thumb.style.transition="";place(over,true);hl(over);
   if(e.cancelable)e.preventDefault();}
  function move(x,e){if(!dragging)return;follow(x);if(e.cancelable)e.preventDefault();}
  function up(){if(!dragging)return;dragging=false;bar.classList.remove("dragging");
   var t=over;place(t,true);hl(t);
   if(t!==curIdx()){try{sessionStorage.setItem("navdir",t>curIdx()?"fwd":"back");}catch(_){}
    setTimeout(function(){location.href=order[t];},130);}}
  if(window.PointerEvent){
   bar.addEventListener("pointerdown",function(e){if(e.button&&e.button!==0)return;
    down(e.clientX,e);try{bar.setPointerCapture(e.pointerId);}catch(_){}});
   bar.addEventListener("pointermove",function(e){move(e.clientX,e);});
   bar.addEventListener("pointerup",up);bar.addEventListener("pointercancel",up);
  }else{
   bar.addEventListener("touchstart",function(e){if(e.touches.length===1)down(e.touches[0].clientX,e);},{passive:false});
   bar.addEventListener("touchmove",function(e){if(e.touches.length===1)move(e.touches[0].clientX,e);},{passive:false});
   bar.addEventListener("touchend",up);bar.addEventListener("touchcancel",up);
  }
  for(var k=0;k<tabs.length;k++)tabs[k].addEventListener("click",function(e){e.preventDefault();});
  addEventListener("resize",function(){place(curIdx(),false);});
 }
 addEventListener("pagereveal",function(e){var d=null;
  try{d=sessionStorage.getItem("navdir");sessionStorage.removeItem("navdir");}catch(_){}
  if(d==="back")document.documentElement.setAttribute("data-navdir","back");});
 if(document.readyState!=="loading")start();else addEventListener("DOMContentLoaded",start);
})();
</script>"""


_NAV_CSS = """<style>
/* iOS 26 風格：置中浮動的玻璃膠囊（外觀玻璃由 GLASS_CSS 提供） */
.tabbar{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(11px + env(safe-area-inset-bottom,0px));
 z-index:60;display:flex;gap:5px;padding:6px;width:min(340px,calc(100vw - 36px));box-sizing:border-box;touch-action:none}
.tabbar a.tab{position:relative;z-index:1;flex:1 1 0;min-width:0;box-sizing:border-box;
 display:flex;flex-direction:column;align-items:center;gap:2px;
 text-decoration:none;color:#aeb8c8;font-size:11px;padding:9px 4px;border-radius:999px;
 transition:color .15s;-webkit-user-drag:none;user-select:none;-webkit-touch-callout:none}
.tabbar a.tab .ic{font-size:20px;line-height:1}
.tabbar a.tab.on,.tabbar a.tab.hl{color:#fff}
.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic{filter:drop-shadow(0 2px 10px rgba(255,80,190,.6))}
/* 無 JS 時用靜態高光；有 JS 時改用可拖曳的玻璃膠囊 .thumb */
.tabbar a.tab.on{background:rgba(255,80,190,.22)}
.tabbar.js a.tab.on{background:transparent}
.tabbar .thumb{position:absolute;top:6px;left:6px;z-index:0;pointer-events:none;border-radius:999px;
 background:rgba(255,80,190,.22);
 transition:left .26s cubic-bezier(.2,.8,.2,1),top .2s,width .2s,height .2s,transform .16s,box-shadow .16s,background .16s}
.tabbar.dragging .thumb{transform:scale(1.12);background:rgba(255,110,205,.34);
 -webkit-backdrop-filter:blur(16px) saturate(1.9);backdrop-filter:blur(16px) saturate(1.9);
 box-shadow:0 12px 30px rgba(0,0,0,.55), inset 0 1px 0.5px rgba(255,255,255,.6), 0 0 0 1px rgba(255,255,255,.22)}
.wrap{padding-top:calc(16px + env(safe-area-inset-top,0px))!important;padding-bottom:calc(84px + env(safe-area-inset-bottom,0px))!important}
/* 切換分頁時內容滑入、底部 bar 不動（原生 View Transitions；不支援則直接切換） */
@view-transition{navigation:auto}
::view-transition-old(root){animation:vtout .24s ease both}
::view-transition-new(root){animation:vtin .32s cubic-bezier(.2,.8,.2,1) both}
@keyframes vtin{from{opacity:0;transform:translateX(26px)}to{opacity:1;transform:translateX(0)}}
@keyframes vtout{from{opacity:1;transform:translateX(0)}to{opacity:0;transform:translateX(-16px)}}
/* 往回滑（→）時，新頁從左邊滑入、舊頁往右滑出 */
:root[data-navdir="back"]::view-transition-new(root){animation-name:vtin-back}
:root[data-navdir="back"]::view-transition-old(root){animation-name:vtout-back}
@keyframes vtin-back{from{opacity:0;transform:translateX(-26px)}to{opacity:1;transform:translateX(0)}}
@keyframes vtout-back{from{opacity:1;transform:translateX(0)}to{opacity:0;transform:translateX(16px)}}
.tabbar{view-transition-name:tabbar}
::view-transition-group(tabbar){animation-duration:.2s}
@media(prefers-reduced-motion:reduce){::view-transition-group(*){animation:none!important}}
</style>"""

# Apple Liquid Glass（深色，盡力逼近）：強霧面 vibrancy + 頂緣鏡面高光 + 折射亮邊 + 連續大圓角。
GLASS_CSS = """<style>
:root{color-scheme:dark}
html{background:#0a1430}
body{background:transparent;color:#f2f5fa}
body::before{content:"";position:fixed;inset:-12%;z-index:-1;pointer-events:none;
 background:
  radial-gradient(1500px 660px at 50% -14%, rgba(72,122,238,.45), transparent 62%),
  radial-gradient(820px 640px at 98% 4%, rgba(60,210,185,.26), transparent 56%),
  radial-gradient(760px 720px at 80% 55%, rgba(255,120,200,.22), transparent 55%),
  radial-gradient(900px 820px at 24% 116%, rgba(150,100,255,.32), transparent 60%),
  linear-gradient(180deg,#12264f,#080e1d 40%,#05070d)}
.card,.box,.pcard,.hero,.brief{position:relative;
 background:linear-gradient(180deg, rgba(255,255,255,.085), rgba(255,255,255,.028))!important;
 -webkit-backdrop-filter:blur(30px) saturate(1.9);backdrop-filter:blur(30px) saturate(1.9);
 border:1px solid rgba(255,255,255,.08)!important;border-radius:24px!important;
 box-shadow:0 16px 46px rgba(0,0,0,.5)!important}
.hero{border-radius:30px!important}
/* 底部浮動分頁列：同款玻璃 + 邊緣高光 */
.tabbar{background:linear-gradient(180deg, rgba(255,255,255,.12), rgba(255,255,255,.05))!important;
 -webkit-backdrop-filter:blur(30px) saturate(1.9);backdrop-filter:blur(30px) saturate(1.9);
 border:1px solid rgba(255,255,255,.14)!important;border-radius:999px!important;
 box-shadow:0 16px 48px rgba(0,0,0,.55), inset 0 1px 0.5px rgba(255,255,255,.5)!important}
.tabbar::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
 box-shadow:inset 0 1px 0.5px rgba(255,255,255,.5), inset 0 0 0 1px rgba(255,255,255,.05);
 background:linear-gradient(135deg, rgba(255,255,255,.10), rgba(255,255,255,0) 45%)}
/* 靜態玻璃：邊緣高光 + 固定柔光（無任何動畫/互動） */
.card::after,.box::after,.pcard::after,.hero::after,.brief::after{
 content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
 box-shadow:inset 0 1px 0.5px rgba(255,255,255,.5), inset 0 0 0 1px rgba(255,255,255,.05);
 background:linear-gradient(125deg, rgba(255,255,255,.085), rgba(255,255,255,0) 42%)}
.navbar{background:linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.025))!important;
 -webkit-backdrop-filter:blur(28px) saturate(1.9);backdrop-filter:blur(28px) saturate(1.9);
 border-bottom:1px solid rgba(255,255,255,.08)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.28)}
.navbar .brand{color:#f2f5fa}.navbar a.tab{color:#cfd8e6}
.navbar a.tab.on{background:rgba(120,170,255,.92)!important;color:#04070d!important;box-shadow:0 3px 16px rgba(120,170,255,.45)}
input{background:rgba(255,255,255,.06)!important;border:1px solid rgba(255,255,255,.12)!important;
 -webkit-backdrop-filter:blur(18px) saturate(1.6);backdrop-filter:blur(18px) saturate(1.6);border-radius:16px!important;color:#f2f5fa}
.searchwrap{background:transparent!important}
.badge{box-shadow:0 3px 16px rgba(0,0,0,.32)}
/* 進階：SVG 位移折射（支援的瀏覽器才套用，否則自動退回上面的模糊） */
@supports (backdrop-filter: url("#lglass")) or (-webkit-backdrop-filter: url("#lglass")){
 .card,.box,.pcard,.hero,.brief,.tabbar{
  -webkit-backdrop-filter:url(#lglass) blur(6px) saturate(2);
  backdrop-filter:url(#lglass) blur(6px) saturate(2)!important}
}
</style>"""

# 真・液態玻璃：用物理算出的「邊緣折射位移圖」(glassmap.png) 做 feImage + feDisplacementMap。
# 中心不動、邊緣像鏡片把背景彎曲。注意：backdrop-filter:url() 主要 Chrome 支援，Safari 多半退回模糊。
GLASS_SVG = ('<svg width="0" height="0" style="position:absolute;pointer-events:none" aria-hidden="true">'
             '<filter id="lglass" x="0%" y="0%" width="100%" height="100%" color-interpolation-filters="sRGB">'
             '<feImage href="glassmap.png" preserveAspectRatio="none" x="0%" y="0%" width="100%" height="100%" result="map"/>'
             # 色散：RGB 三通道各以不同位移量折射，邊緣產生彩虹色散（chromatic aberration，Chrome 可見）
             '<feDisplacementMap in="SourceGraphic" in2="map" scale="30" xChannelSelector="R" yChannelSelector="G" result="dR"/>'
             '<feDisplacementMap in="SourceGraphic" in2="map" scale="34" xChannelSelector="R" yChannelSelector="G" result="dG"/>'
             '<feDisplacementMap in="SourceGraphic" in2="map" scale="38" xChannelSelector="R" yChannelSelector="G" result="dB"/>'
             '<feColorMatrix in="dR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cR"/>'
             '<feColorMatrix in="dG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cG"/>'
             '<feColorMatrix in="dB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="cB"/>'
             '<feBlend in="cR" in2="cG" mode="screen" result="rg"/>'
             '<feBlend in="rg" in2="cB" mode="screen"/>'
             '</filter></svg>')


def nav(active="", include_css=False):
    """底部分頁列（iOS 風格）。消息＝首頁。回測收進大盤子頁，不在主分頁。
    active ∈ news/index/stocks（在回測頁傳 index，視為大盤子頁）。"""
    tabs = [("news.html", "news", "📰", "消息"), ("index.html", "index", "📊", "大盤"),
            ("perspectives.html", "debate", "🗣️", "觀點"), ("stocks.html", "stocks", "📈", "個股")]
    items = "".join('<a class="tab%s" href="%s"><span class="ic">%s</span><span>%s</span></a>'
                    % (" on" if k == active else "", href, ic, lb) for href, k, ic, lb in tabs)
    css = (_NAV_CSS + GLASS_CSS) if include_css else ""
    return css + GLASS_SVG + '<nav class="tabbar">' + items + '</nav>' + SWIPE_JS


def render(result: Dict, indicators: List[Dict], score_history: List, meta: Dict,
           regime: Dict = None, cycle: Dict = None, forecast: List = None,
           perspectives: List = None) -> str:
    from config import REFRESH_SECONDS
    parts: List[str] = [_HEAD.replace("__REFRESH__", str(REFRESH_SECONDS))]
    parts.append(nav("index", include_css=True))
    parts.append('<div class="wrap">')

    parts.append('<h1>市場進場儀表板 <span style="font-size:14px;color:var(--muted)">台股・美股</span></h1>')
    parts.append('<div class="sub">資料時間：%s　｜　綜合進場分數越高＝越適合分批加碼（較主動的定期定額）</div>'
                 % _esc(meta.get("generated_at", "")))

    failed = meta.get("sources_failed") or []
    if failed:
        parts.append('<div class="warn">部分資料源本次無法取得，已自動跳過並重新分配權重：%s</div>'
                     % _esc("、".join(failed)))

    # Hero
    band_color = {"積極加碼區": "green", "加碼區": "green", "正常定額區": "amber",
                  "減碼觀望區": "red", "保守防禦區": "red"}.get(result["band"], "amber")
    parts.append('<div class="hero"><div id="gauge"></div><div class="verdict">')
    parts.append('<span class="badge" style="background:var(--%s);color:#0e1116">%s</span>'
                 % (band_color, _esc(result["band"])))
    parts.append('<h2>進場分數 %.1f</h2>' % result["composite"])
    parts.append('<p>%s</p>' % _esc(result["action"]))
    # 0–100 分數圖例（對應儀表板色帶與建議倍數）
    parts.append('<div class="legend" style="display:flex;flex-wrap:wrap;gap:7px 10px;margin:6px 0 2px">'
                 + ''.join(
                     '<span style="white-space:nowrap;font-size:11.5px">'
                     '<span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
                     'background:%s;margin-right:3px"></span>%s</span>' % (c, t)
                     for c, t in [("var(--red)", "0–35 保守"), ("#f6862a", "35–45 減碼"),
                                  ("var(--amber)", "45–58 正常定額"), ("#7cc24a", "58–70 加碼"),
                                  ("var(--green)", "70–100 積極加碼")])
                 + '</div>')
    parts.append('<div class="mult">建議定額倍數：<b>%.2gx</b> <span style="color:var(--muted)">'
                 '（相對平常每月定額金額）</span></div>' % result["dca_multiplier"])
    if result.get("news_delta"):
        _nd = result["news_delta"]
        _ncol = "green" if _nd > 0 else "red"
        parts.append('<div style="font-size:12.5px;color:var(--muted);margin-top:8px">'
                     '已含<b>消息面微調 <span class="" style="color:var(--%s)">%+.1f</span></b>'
                     '（量化基準 %.1f）<br>%s</div>'
                     % (_ncol, _nd, result.get("composite_base", result["composite"]),
                        _esc(result.get("news_reason") or "")))
    parts.append('<div id="score-hist" class="hist"></div>')
    n_hist = len(score_history) if score_history else 0
    if n_hist >= 2:
        parts.append('<div style="font-size:11px;color:var(--muted);margin-top:2px">'
                     '綜合分數走勢（近 %d 日，含回測；滑過看數值）</div>' % n_hist)
    else:
        parts.append('<div style="font-size:11px;color:var(--muted);margin-top:2px">'
                     '綜合分數走勢將於累積數日後顯示</div>')
    parts.append('</div></div>')

    # Pillars
    parts.append('<div class="pillars">')
    for p in result["pillars"]:
        parts.append(
            '<div class="pcard"><div class="pn">%s</div>'
            '<div class="ps" style="color:var(--%s)">%.0f</div>'
            '<div class="pw">權重 %d%%・%d 指標</div></div>'
            % (_esc(p["name"]), p["light"], p["score"], p["weight"], p["n"]))
    parts.append('</div>')

    # 策略回測：直接內嵌績效（不用點進去）
    _bt = None
    try:
        import json as _json, os as _os
        import config as _cfg
        _bt_path = _os.path.join(_cfg.DATA_DIR, "backtest_summary.json")
        if _os.path.exists(_bt_path):
            with open(_bt_path, encoding="utf-8") as _f:
                _bt = _json.load(_f)
    except Exception:
        _bt = None
    if _bt:
        parts.append('<div class="section-title">策略回測：主動 vs 固定定期定額 '
                     '<a href="backtest.html" style="font-size:12px;color:#5b9cff;font-weight:400;margin-left:8px">完整報告 →</a></div>')
        parts.append('<div class="grid">')
        for sym, blk in _bt.get("symbols", {}).items():
            best_irr = max((r["irr"] for r in blk["rows"].values() if r["irr"] is not None), default=None)
            parts.append('<div class="card" style="grid-template-columns:1fr">')
            parts.append('<div class="name" style="font-size:15px;font-weight:700;margin-bottom:10px">%s</div>' % _esc(blk["label"]))
            parts.append('<table style="width:100%;border-collapse:collapse;font-size:13px">'
                         '<thead><tr style="color:var(--muted)">'
                         '<th style="text-align:left;padding:5px 4px">策略</th>'
                         '<th style="text-align:right">年化IRR</th>'
                         '<th style="text-align:right">報酬%</th>'
                         '<th style="text-align:right">最大回撤</th></tr></thead><tbody>')
            for name, r in blk["rows"].items():
                is_best = (r["irr"] is not None and r["irr"] == best_irr)
                col = "color:#28c76f;font-weight:700" if is_best else ""
                parts.append('<tr style="border-bottom:1px solid rgba(255,255,255,.06)">'
                             '<td style="padding:5px 4px;%s">%s</td>'
                             '<td style="text-align:right;%s">%s</td>'
                             '<td style="text-align:right">%+.1f%%</td>'
                             '<td style="text-align:right">%.1f%%</td></tr>'
                             % (col, _esc(name), col,
                                ("%.1f%%" % r["irr"]) if r["irr"] is not None else "—",
                                r["ret"], r["maxdd"]))
            parts.append('</tbody></table>')
            cid = "btch_" + "".join(c if c.isalnum() else "_" for c in sym)
            parts.append('<div id="%s" style="height:340px;margin-top:12px"></div>' % cid)
            parts.append('</div>')
        parts.append('</div>')
        # ECharts 圖表注入：延後到頁面載入後再 init（容器才有寬度，否則畫成空白）
        _btcharts = {}
        for sym, blk in _bt.get("symbols", {}).items():
            ch = blk.get("chart", {})
            if ch.get("labels"):
                cid = "btch_" + "".join(c if c.isalnum() else "_" for c in sym)
                _btcharts[cid] = ch
        if _btcharts:
            parts.append('<script>(function(){var BT=%s;' % json.dumps(_btcharts, ensure_ascii=False))
            parts.append('function init(){if(typeof echarts==="undefined")return;'
                         'Object.keys(BT).forEach(function(id){var el=document.getElementById(id);if(!el)return;'
                         'var d=BT[id];var c=echarts.init(el);'
                         'c.setOption({grid:{left:46,right:14,top:34,bottom:28},'
                         'legend:{data:["固定定額","主動・逆勢"],textStyle:{color:"#cdd5e3"},top:4},'
                         'tooltip:{trigger:"axis"},'
                         'xAxis:{type:"category",data:d.labels,axisLabel:{color:"#8590a3",fontSize:10}},'
                         'yAxis:{type:"value",scale:true,axisLabel:{color:"#8590a3",fontSize:10,formatter:function(v){return v.toFixed(2);}}},'
                         'series:[{name:"固定定額",type:"line",data:d.fixed,smooth:true,symbol:"none",lineStyle:{color:"#94a0b4",width:2}},'
                         '{name:"主動・逆勢",type:"line",data:d.active,smooth:true,symbol:"none",lineStyle:{color:"#5b9cff",width:2.5}}]});'
                         'setTimeout(function(){c.resize();},60);'
                         'window.addEventListener("resize",function(){c.resize();});});}'
                         'if(document.readyState==="complete"){init();}else{window.addEventListener("load",init);}'
                         '})();</script>')
    else:
        # JSON 還沒產生時的 fallback
        parts.append('<a href="backtest.html" style="display:inline-block;margin:2px 0 4px;padding:9px 16px;'
                     'background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:13px;'
                     'color:#9ec1ff;font-size:13.5px;text-decoration:none">📊 策略回測：主動 vs 固定定期定額 →</a>')

    # 多派觀點已獨立成「🗣️ 觀點」分頁，這裡只放入口
    if perspectives and len(perspectives) > 1:
        parts.append('<div class="section-title">市場觀點・三方辯論</div>')
        parts.append('<div class="card" style="grid-template-columns:1fr"><div class="note" style="grid-column:1/3">'
                     '同一份數據，三種投資流派（被動／總經／紀律）如何解讀、彼此激烈辯論並收斂出結論 → '
                     '<a href="perspectives.html">看「🗣️ 觀點」分頁 →</a>'
                     '<br><span style="color:var(--muted);font-size:12px">以公開投資流派為框架・非本人發言・非投資建議</span>'
                     '</div></div>')

    # AI 噴發 / 泡沫 情境面板
    if regime:
        st = regime.get("status", "正常")
        st_color = {"噴發中": "amber", "高檔轉弱": "red", "正常": "green"}.get(st, "amber")
        frag = regime.get("fragility", 0)
        fl = regime.get("fragility_light", "amber")
        parts.append('<div class="section-title">AI 噴發 / 泡沫 情境</div>')
        parts.append('<div class="card" style="grid-template-columns:1fr">')
        parts.append('<div class="top" style="justify-content:space-between">'
                     '<div><span class="dot" style="background:var(--%s)"></span>'
                     '<span class="name" style="font-size:16px">狀態：%s</span></div>'
                     '<div style="font-size:12px;color:var(--muted)">泡沫脆弱度（越高越像晚期泡沫）</div></div>'
                     % (st_color, _esc(st)))
        parts.append('<div class="barwrap" style="grid-column:1/3"><div class="bar">'
                     '<i style="width:%.0f%%;background:var(--%s)"></i></div>'
                     '<div class="scoretxt">脆弱度 %d / 100</div></div>' % (frag, fl, frag))
        parts.append('<div class="note" style="grid-column:1/3">%s</div>' % _esc(regime.get("status_note", "")))
        # 組成
        parts.append('<div style="grid-column:1/3;display:grid;grid-template-columns:repeat(2,1fr);gap:6px 16px;'
                     'margin-top:6px;font-size:12.5px">')
        for label, disp, fr in regime.get("components", []):
            c = "red" if fr >= 66 else "amber" if fr >= 40 else "green"
            parts.append('<div style="display:flex;justify-content:space-between;gap:8px">'
                         '<span style="color:var(--muted)">%s</span>'
                         '<span style="color:var(--%s);text-align:right">%s</span></div>'
                         % (_esc(label), c, _esc(disp)))
        parts.append('</div>')
        if regime.get("derisk_text"):
            parts.append('<div class="detail" style="grid-column:1/3">%s</div>' % _esc(regime["derisk_text"]))
        if meta.get("meltup_aware"):
            parts.append('<div class="note" style="grid-column:1/3;color:var(--accent)">'
                         '噴發感知已開啟：噴發期定額倍數已設下限，改以跌破 50 日線為減碼訊號。</div>')
        parts.append('</div>')

    # 景氣循環（投資時鐘）面板
    if cycle:
        ph = cycle.get("phase", "")
        col = cycle.get("color", "amber")
        parts.append('<div class="section-title">景氣循環階段（投資時鐘）</div>')
        parts.append('<div class="card" style="grid-template-columns:1fr">')
        parts.append('<div class="top" style="justify-content:space-between">'
                     '<div><span class="dot" style="background:var(--%s)"></span>'
                     '<span class="name" style="font-size:16px">階段：%s</span></div>'
                     '<div style="font-size:12px;color:var(--muted)">%s</div></div>'
                     % (col, _esc(ph), _esc(cycle.get("position", ""))))
        parts.append('<div class="note" style="grid-column:1/3">%s</div>' % _esc(cycle.get("implication", "")))
        parts.append('<div style="grid-column:1/3;display:grid;grid-template-columns:repeat(3,1fr);'
                     'gap:6px 16px;margin-top:6px;font-size:12.5px">')
        for label, disp, c in cycle.get("components", []):
            parts.append('<div><div style="color:var(--muted)">%s</div>'
                         '<div style="color:var(--%s)">%s</div></div>'
                         % (_esc(label), c, _esc(disp)))
        parts.append('</div></div>')

    # 歷史條件式預期（base rates）
    if forecast:
        parts.append('<div class="section-title">歷史條件式預期（過去同類情況的後續・非保證）</div>')
        parts.append('<div class="grid">')
        for t in forecast:
            parts.append('<div class="card">')
            parts.append('<div class="top"><span class="dot" style="background:var(--%s)"></span>'
                         '<div><div class="name">%s</div>'
                         '<div class="val">距200日均 %+.0f%%（第%d十分位）→ 歷史機率 %s</div></div></div>'
                         % (t.get("lean_light", "amber"), _esc(t["label"]), t["ext"] * 100,
                            t["decile"], _esc(t["lean"])))
            for h in t["horizons"]:
                c = "green" if h["mean"] > 0 else "red"
                parts.append('<div class="note" style="grid-column:1/3;display:flex;justify-content:space-between">'
                             '<span class="muted">未來%s</span>'
                             '<span class="%s">平均 %+.1f%%</span>'
                             '<span class="muted">上漲機率 %.0f%%</span>'
                             '<span class="muted">樣本 %d</span></div>'
                             % (_esc(h["label"]), c, h["mean"] * 100, h["win"] * 100, h["n"]))
            parts.append('</div>')
        parts.append('</div>')
        parts.append('<div class="note" style="margin-top:6px">依「距200日均乖離」的歷史十分位推估，'
                     '過去≠未來、樣本有限，僅為客觀基準、<b>非預測也非投資建議</b>。</div>')

    # Indicators grouped by pillar
    from config import PILLAR_NAMES
    by_cat: Dict[str, List[Dict]] = {}
    for ind in indicators:
        by_cat.setdefault(ind["category"], []).append(ind)
    for cat in PILLAR_WEIGHTS:
        items = by_cat.get(cat)
        if not items:
            continue
        parts.append('<div class="section-title">%s</div><div class="grid">'
                     % _esc(PILLAR_NAMES.get(cat, cat)))
        for ind in items:
            parts.append('<div class="card">')
            parts.append('<div class="top"><span class="dot" style="background:var(--%s)"></span>'
                         '<div><div class="name">%s</div><div class="val">%s</div></div></div>'
                         % (ind["light"], _esc(ind["name"]), _esc(ind["value_display"])))
            parts.append('<div class="barwrap"><div class="bar"><i style="width:%.0f%%;background:var(--%s)"></i></div>'
                         '<div class="scoretxt">進場機會分數 %.0f / 100</div></div>'
                         % (ind["score"], ind["light"], ind["score"]))
            parts.append('<div class="spark" id="spark-%s"></div>' % _esc(ind["key"]))
            parts.append('<div class="note">%s</div>' % _esc(ind["note"]))
            if ind.get("detail"):
                parts.append('<div class="detail">%s</div>' % _esc(ind["detail"]))
            parts.append('</div>')
        parts.append('</div>')

    # Footer
    parts.append('<div class="foot">')
    parts.append('<div class="legend"><span>🟢 偏多／加碼</span><span>🟡 中性</span><span>🔴 偏空／保守</span></div>')
    parts.append('資料來源：Yahoo Finance、美國勞工統計局(BLS) CPI、美國財政部殖利率曲線、'
                 '臺灣證交所(TWSE) 三大法人／融資融券／估值／成交量、櫃買中心(TPEX) 三大法人、'
                 '國家發展委員會 景氣對策信號。<br>')
    parts.append('本頁為個人研究與決策輔助工具，所有指標與分數僅供參考，<b>不構成任何投資建議</b>，'
                 '投資前請自行評估風險。<br>')
    parts.append('共 %d 項指標・產生時間 %s' % (result["n_indicators"], _esc(meta.get("generated_at", ""))))
    parts.append('</div>')

    # Inject data
    dash = {
        "composite": result["composite"],
        "score_history": score_history,
        "indicators": [{"key": i["key"], "series": i["series"], "light": i["light"]} for i in indicators],
    }
    parts.append('<script>const DASH=%s;</script>'
                 % json.dumps(dash, ensure_ascii=False))
    parts.append(_TAIL)
    return with_pwa("".join(parts))


def render_perspectives_page(perspectives: List, meta: Dict) -> str:
    """獨立的「🗣️ 觀點」分頁：三方立場辯論 + 結論。寫出 output/perspectives.html。"""
    import os
    from config import REFRESH_SECONDS
    p: List[str] = [_HEAD.replace("__REFRESH__", str(REFRESH_SECONDS))]
    p.append(nav("debate", include_css=True))
    p.append('<div class="wrap">')
    p.append('<h1>🗣️ 市場觀點・三方辯論 <span style="font-size:14px;color:var(--muted)">同一份數據・三種解讀</span></h1>')
    p.append('<div class="sub">資料時間：%s　｜　以公開投資流派為「框架」推演・<b>非本人發言・非投資建議</b></div>'
             % _esc(meta.get("generated_at", "")))
    if perspectives and len(perspectives) > 1:
        p.append('<div class="section-title">三方立場</div>')
        p.append('<div class="grid">')
        for pp in perspectives[1:]:
            p.append('<div class="card">')
            p.append('<div class="top"><span class="dot" style="background:var(--%s)"></span>'
                     '<div><div class="name">%s</div><div class="val">%s → %s</div></div></div>'
                     % (pp.get("lean_light", "amber"), _esc(pp["name"]),
                        _esc(pp["school"]), _esc(pp["lean"])))
            p.append('<div class="note" style="grid-column:1/3">%s</div>' % _esc(pp["take"]))
            p.append('<div class="detail" style="grid-column:1/3">原則：%s</div>' % _esc(pp["principles"]))
            p.append('</div>')
        p.append('</div>')
        # 🔥 三方互嗆（交鋒對話）
        deb = perspectives[0].get("debate")
        if deb:
            n2l = {pp["name"]: pp.get("lean_light", "amber") for pp in perspectives[1:]}
            p.append('<div class="section-title">🔥 三方互嗆</div>')
            p.append('<div class="card" style="grid-template-columns:1fr">')
            for i, (frm, to, line) in enumerate(deb):
                col = n2l.get(frm, "amber")
                side = "right" if i % 2 else "left"
                align = "margin-left:auto;" if i % 2 else ""
                p.append('<div style="grid-column:1/3;max-width:90%;' + align +
                         'margin-bottom:10px;background:var(--panel2);border-' + side +
                         ':3px solid var(--' + col + ');border-radius:12px;padding:10px 13px">'
                         '<div style="font-size:12px;font-weight:700;color:var(--' + col + ')">' + _esc(frm) +
                         ' <span style="color:var(--muted);font-weight:400">嗆 ' + _esc(to) + '</span></div>'
                         '<div style="font-size:14.5px;margin-top:4px;color:var(--text)">' + _esc(line) + '</div></div>')
            p.append('</div>')
        syn = perspectives[0].get("synthesis")
        if syn:
            p.append('<div class="section-title">辯論結論</div>')
            p.append('<div class="card" style="grid-template-columns:1fr">'
                     '<div class="note" style="grid-column:1/3;white-space:pre-wrap;line-height:1.7">%s</div></div>'
                     % _esc(syn))
    else:
        p.append('<div class="card"><div class="note">本次無觀點資料。</div></div>')
    p.append('</div></body></html>')
    html = with_pwa("".join(p))
    import config as cfg
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(cfg.OUTPUT_DIR, "perspectives.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return "perspectives.html"
