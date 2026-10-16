"use strict";
// Saved timestamps are preserved. Cached views paint immediately while fresh
// prepared data is checked; no observation collection runs in the browser.
window.WeatherData = (() => {
  const memory=new Map(),pending=new Map(),assetsPending=new Map();
  const jsonCache="weather-json-v1",assetCache="weather-assets-v1",maxSavedAge=48*3600000;
  function remember(url,entry){memory.delete(url);memory.set(url,entry);while(memory.size>40)memory.delete(memory.keys().next().value);}
  async function cache(name){try{return typeof caches!=="undefined"?await caches.open(name):null;}catch{return null;}}
  async function trim(store,limit){const keys=await store.keys();await Promise.all(keys.slice(0,Math.max(0,keys.length-limit)).map(key=>store.delete(key)));}
  async function saved(url){
    let entry=memory.get(url);
    if(!entry){
      try{const store=await cache(jsonCache),response=await store?.match(url);if(response)entry=await response.json();}catch{}
      if(entry)remember(url,entry);
    }
    return entry&&Date.now()-entry.savedAt>=0&&Date.now()-entry.savedAt<maxSavedAge?entry:null;
  }
  async function json(url,{maxAge=30000,onCached}={}){
    const entry=await saved(url);
    if(entry&&Date.now()-entry.savedAt<maxAge)return entry.value;
    if(entry&&onCached){try{Promise.resolve(onCached(entry.value)).catch(()=>{});}catch{}}
    if(!pending.has(url)){
      const work=(async()=>{
        const response=await fetch(url,{cache:"no-store"}),value=await response.json();
        if(!response.ok)throw Error(value.error||"Weather data temporarily unavailable");
        const next={savedAt:Date.now(),value};remember(url,next);
        // Disk cache writes are best-effort and never delay rendering.
        cache(jsonCache).then(async store=>{if(store){await store.put(url,new Response(JSON.stringify(next),{headers:{"Content-Type":"application/json"}}));await trim(store,40);}}).catch(()=>{});
        return value;
      })();
      pending.set(url,work);work.finally(()=>pending.delete(url)).catch(()=>{});
    }
    return pending.get(url);
  }
  async function asset(url){
    const store=await cache(assetCache);
    try{const found=await store?.match(url);if(found)return found;}catch{}
    if(!assetsPending.has(url)){
      const work=(async()=>{
        const response=await fetch(url,{cache:"force-cache"});
        if(!response.ok)throw Error("Prepared image or scan unavailable");
        if(store)store.put(url,response.clone()).then(()=>trim(store,64)).catch(()=>{});
        return response;
      })();
      assetsPending.set(url,work);work.finally(()=>assetsPending.delete(url)).catch(()=>{});
    }
    return (await assetsPending.get(url)).clone();
  }
  async function image(url){
    await asset(url);
    if(typeof Image!=="undefined"){const img=new Image();img.src=url;if(img.decode)await img.decode().catch(()=>{});}
  }
  async function warmMaps(index){
    const latest=index.history?.at(-1);if(!latest?.analysisUrl)return;
    const manifest=await json(latest.analysisUrl,{maxAge:Infinity});
    await Promise.allSettled(Object.values(manifest.fields).map(field=>image(field.imageUrl)));
  }
  async function warmRadar(index){const latest=index.frames?.at(-1);if(latest)await asset(latest.url);}
  function prime(){
    json("/api/station-plots",{maxAge:30000}).catch(()=>{});
    json("/api/maps",{maxAge:30000,onCached:warmMaps}).then(warmMaps).catch(()=>{});
    json("/api/radar?site=KMPX",{maxAge:15000,onCached:warmRadar}).then(warmRadar).catch(()=>{});
  }
  return {json,asset,image,prime};
})();
