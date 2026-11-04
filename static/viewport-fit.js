"use strict";
// Size the app to the browser's visible area, including iPhone toolbar changes.
window.WeatherLayout = (() => {
  let queued=false;
  const appMode=window.matchMedia?.("(display-mode: standalone)");
  function mode(){
    document.documentElement.classList?.toggle("installed-web-app",Boolean(appMode?.matches||window.navigator?.standalone));
  }
  function notify(){
    if(queued)return;queued=true;
    window.requestAnimationFrame(()=>{queued=false;window.dispatchEvent(new Event("weather-layout-resize"));});
  }
  function fit(){
    mode();
    const viewport=window.visualViewport;
    // Page magnification should not continually shrink and reflow the app.
    if(!viewport||Math.abs(viewport.scale-1)<.01){
      const height=Math.round(viewport?.height||window.innerHeight);
      if(height>0)document.documentElement.style.setProperty("--app-height",`${height}px`);
    }
    notify();
  }
  window.addEventListener("resize",fit);
  window.addEventListener("pageshow",fit);
  window.addEventListener("orientationchange",fit);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)fit();});
  appMode?.addEventListener?.("change",fit);
  window.visualViewport?.addEventListener("resize",fit);
  if(typeof ResizeObserver!=="undefined"){
    const observer=new ResizeObserver(notify);
    document.querySelectorAll(".map-area").forEach(element=>observer.observe(element));
  }
  fit();
  return {fit};
})();
