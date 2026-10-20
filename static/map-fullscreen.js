"use strict";
// All map surfaces include their own timeline and exit control.
window.WeatherFullscreen = (() => {
  const views=[];
  const active=view=>document.fullscreenElement===view.surface||view.surface.classList.contains("expanded");
  const resize=view=>window.requestAnimationFrame(()=>view.onResize());
  function sync() {
    for(const view of views){
      const expanded=active(view);
      view.wasActive=expanded;
      view.button.textContent=expanded?"Close":"Full screen";
      view.button.setAttribute("aria-label",`${expanded?"Close full-screen":"Open full-screen"} ${view.label}`);
      view.button.setAttribute("aria-expanded",String(expanded));
    }
    document.body.classList.toggle("map-expanded",views.some(view=>view.surface.classList.contains("expanded")));
  }
  function collapse(view) {
    view.surface.classList.remove("expanded");sync();resize(view);
    view.button.focus({preventScroll:true});
  }
  function attach({surfaceId,buttonId,label,onResize}) {
    const view={surface:document.getElementById(surfaceId),button:document.getElementById(buttonId),label,onResize};
    views.push(view);view.button.setAttribute("aria-controls",surfaceId);sync();
    let busy=false;
    view.button.addEventListener("click",async()=>{
      if(busy)return;busy=true;
      try{
        if(view.surface.classList.contains("expanded")){collapse(view);return;}
        if(document.fullscreenElement===view.surface){await document.exitFullscreen();return;}
        for(const other of views)if(other.surface.classList.contains("expanded"))collapse(other);
        if(document.fullscreenElement)await document.exitFullscreen();
        try{
          if(typeof view.surface.requestFullscreen!=="function")throw Error("Fullscreen unavailable");
          await view.surface.requestFullscreen({navigationUI:"hide"});
        }catch(_){
          // iPhone and embedded browsers can fill the available viewport even
          // when native fullscreen is unsupported or the browser rejects it.
          view.surface.classList.add("expanded");
        }
      }finally{busy=false;sync();resize(view);}
    });
  }
  document.addEventListener("fullscreenchange",()=>{
    const changed=views.filter(view=>active(view)||view.wasActive);
    sync();for(const view of changed)resize(view);
  });
  document.addEventListener("keydown",event=>{
    if(event.key==="Escape")for(const view of views)if(view.surface.classList.contains("expanded")){event.preventDefault();collapse(view);}
  });
  const resizeActive=()=>{for(const view of views)if(active(view))resize(view);};
  window.addEventListener("resize",resizeActive);
  window.visualViewport?.addEventListener("resize",resizeActive);
  return {attach};
})();
