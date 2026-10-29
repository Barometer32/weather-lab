"use strict";
// Expand the entire weather app so navigation and timelines stay available.
window.WeatherFullscreen = (() => {
  const views=[],root=document.documentElement;
  let busy=false,wasNative=false;
  const active=()=>document.fullscreenElement===root||document.body.classList.contains("map-focus");
  const resize=()=>window.requestAnimationFrame(()=>{for(const view of views)view.onResize();});
  function sync(){
    const expanded=active();
    for(const view of views){
      view.button.textContent=expanded?"Close":"Full screen";
      view.button.setAttribute("aria-label",`${expanded?"Close full-screen":"Open full-screen"} ${view.label}`);
      view.button.setAttribute("aria-expanded",String(expanded));
    }
  }
  async function close(){
    document.body.classList.remove("map-focus");
    if(document.fullscreenElement===root)await document.exitFullscreen();
    sync();resize();
  }
  function attach({surfaceId,buttonId,label,onResize}){
    const view={surface:document.getElementById(surfaceId),button:document.getElementById(buttonId),label,onResize};
    views.push(view);view.button.setAttribute("aria-controls",surfaceId);sync();
    view.button.addEventListener("click",async()=>{
      if(busy)return;busy=true;
      try{
        if(active()){await close();view.button.focus({preventScroll:true});return;}
        document.body.classList.add("map-focus");
        // Native fullscreen is optional. The same layout fills Safari's visible
        // area when it is unsupported, and the tab bar remains part of the app.
        try{if(typeof root.requestFullscreen==="function")await root.requestFullscreen({navigationUI:"hide"});}catch(_){}
      }finally{busy=false;sync();resize();}
    });
  }
  document.addEventListener("fullscreenchange",()=>{
    const native=document.fullscreenElement===root;
    if(wasNative&&!native)document.body.classList.remove("map-focus");
    wasNative=native;sync();resize();
  });
  document.addEventListener("keydown",event=>{
    if(event.key==="Escape"&&active()){event.preventDefault();close();}
  });
  const resizeActive=()=>{if(active())resize();};
  window.addEventListener("resize",resizeActive);
  window.visualViewport?.addEventListener("resize",resizeActive);
  return {attach,select(id){if(!["radar","metar","satellite"].includes(id)&&active())close();}};
})();
