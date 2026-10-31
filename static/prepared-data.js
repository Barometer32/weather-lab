"use strict";
// Saved JSON paints first; current prepared objects refresh in the background.
// Imagery URLs are immutable and use the browser's existing HTTP cache.
window.WeatherPrepared = (() => {
  const cacheName="weather-prepared-metar-v1",memory=new Map(),pending=new Map(),listeners=new Map();
  const images=new Map(),radars=new Map(),assetQueue=[],queued=new Set();
  let warming=false,workers=0;
  const paths=["/api/station-plots","/api/hennepin-current","/api/radar?site=KMPX","/api/forecast","/api/satellite/13","/api/satellite/truecolor","/api/satellite/dcphase","/api/satellite/ntmicro","/api/air-quality"];
  const maxSavedAge=url=>url.includes("station-plots")?3600000:url.includes("forecast")?21600000:url.includes("air-quality")?10800000:900000;
  const freshFor=url=>url.includes("radar")?15000:30000;
  async function disk(){try{return await window.caches?.open(cacheName);}catch(_){return null;}}
  async function remember(url,data,stamp){
    try{const cache=await disk();if(cache)await cache.put(url,new Response(JSON.stringify(data),{headers:{"Content-Type":"application/json","X-Weather-Saved-At":String(stamp)}}));}catch(_){}
  }
  function subscribe(url,callback){
    if(!listeners.has(url))listeners.set(url,new Set());listeners.get(url).add(callback);
    return ()=>listeners.get(url)?.delete(callback);
  }
  async function refresh(url){
    if(pending.has(url))return pending.get(url);
    const work=(async()=>{
      try{
        const response=await fetch(url,{cache:"no-store"}),data=await response.json();
        if(!response.ok)throw Error(data.error||"Prepared weather data unavailable.");
        const stamp=Date.now();memory.set(url,{data,stamp});remember(url,data,stamp);
        if(warming)warmManifest(url,data);
        for(const callback of listeners.get(url)||[]){try{callback(data);}catch(_){}}
        return data;
      }finally{pending.delete(url);}
    })();pending.set(url,work);return work;
  }
  async function read(url,{force=false}={}){
    if(!paths.includes(url))throw Error("Unknown prepared weather endpoint");
    const old=memory.get(url);
    if(!force&&old&&Date.now()-old.stamp<freshFor(url))return old.data;
    const work=refresh(url);work.catch(()=>{});
    if(force)return work;
    if(old&&Date.now()-old.stamp<maxSavedAge(url))return {...old.data,_savedCopy:true};
    try{
      const cache=await disk(),response=await cache?.match(url);
      const stamp=Number(response?.headers.get("X-Weather-Saved-At"));
      if(response&&Number.isFinite(stamp)&&Date.now()-stamp<maxSavedAge(url)){
        // A faster network response must never be overwritten by the disk copy.
        if(memory.has(url))return memory.get(url).data;
        const data={...await response.json(),_savedCopy:true};
        if(memory.has(url))return memory.get(url).data;
        memory.set(url,{data,stamp:0});return data;
      }
    }catch(_){}
    return work;
  }
  async function bytes(url){
    const response=await fetch(url,{cache:"force-cache"});
    if(!response.ok)throw Error("Prepared weather file unavailable");
    return response.arrayBuffer();
  }
  function trim(map,limit){while(map.size>limit)map.delete(map.keys().next().value);}
  function radar(frame,manifest){
    const key=frame.url;
    if(!radars.has(key)){
      const promise=bytes(key).then(buffer=>{
        const decoded=window.NativeRadar.decode(buffer);
        if(decoded.meta.site!==manifest.site||decoded.meta.id!==frame.id)throw Error("Radar scan mismatch");
        return decoded;
      }).catch(error=>{radars.delete(key);throw error;});
      radars.set(key,promise);trim(radars,64);
    }
    return radars.get(key);
  }
  function image(url){
    if(!images.has(url)){
      const picture=new Image();picture.src=url;
      images.set(url,picture.decode().then(()=>picture).catch(error=>{images.delete(url);throw error;}));trim(images,4);
    }
    return images.get(url);
  }
  function queue(url,work,priority=false){
    if(!url?.startsWith("/api/prepared/")||queued.has(url))return;
    queued.add(url);const item={url,work};priority?assetQueue.unshift(item):assetQueue.push(item);drain();
  }
  function drain(){
    while(workers<2&&assetQueue.length&&!document.hidden){
      const item=assetQueue.shift();workers++;
      Promise.resolve().then(item.work).catch(()=>queued.delete(item.url)).finally(()=>{workers--;drain();});
    }
  }
  function warmManifest(url,data){
    if(url.includes("radar")){
      const frames=data.frames||[],latest=frames.at(-1);
      if(latest)queue(latest.url,()=>radar(latest,data),true);
      for(const frame of [...frames].reverse())queue(frame.url,()=>radar(frame,data));
    }else if(url.includes("satellite")||url.includes("air-quality")){
      const frames=data.frames||[],latest=frames.at(-1);
      if(latest)queue(latest.url,()=>image(latest.url),true);
      for(const boundary of data.boundaries||[])queue(boundary,()=>bytes(boundary),true);
      for(const frame of [...frames].reverse())queue(frame.url,()=>bytes(frame.url));
    }
    // Keep memory bounded over a long-running page as manifests advance.
    if(queued.size>256){const active=new Set(assetQueue.map(item=>item.url));for(const key of queued)if(!active.has(key)&&queued.size>192)queued.delete(key);}
  }
  async function prime(){
    warming=true;
    // Give the initial METAR display priority before older imagery transfers.
    try{await read("/api/station-plots");}catch(_){}
    return Promise.allSettled(paths.slice(1).map(async url=>{const data=await read(url);warmManifest(url,data);}));
  }
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)drain();});
  return {read,subscribe,prime,radar,image};
})();
