"use strict";
// Saved JSON paints first; current prepared objects refresh in the background.
// Imagery URLs are immutable and use the browser's existing HTTP cache.
window.WeatherPrepared = (() => {
  const cacheName="weather-prepared-metar-v1",memory=new Map(),pending=new Map(),listeners=new Map();
  const images=new Map(),radars=new Map();
  const metarLoop="/api/station-plots?view=loop";
  const observations="/api/observations/hourly?view=table";
  const radarManifest="/api/radar?site=KMPX",satelliteManifest="/api/satellite/truecolor";
  const paths=[metarLoop,observations,radarManifest,"/api/forecast",satelliteManifest,"/api/satellite/dcphase","/api/satellite/ntmicro","/api/air-quality"];
  const maxSavedAge=url=>url===observations?3600000:url.includes("station-plots")?3600000:url.includes("forecast")?21600000:url.includes("air-quality")?10800000:900000;
  const freshFor=url=>url.includes("radar")?15000:30000;
  async function disk(){try{return await window.caches?.open(cacheName);}catch(_){return null;}}
  // Drop retired product manifests without disturbing other saved weather.
  disk().then(cache=>cache&&Promise.all([
    cache.delete("/api/satellite/13"),
    cache.delete("/api/hrmetar",{ignoreSearch:true}),
    cache.delete("/api/observation-stations?view=mesonet",{ignoreSearch:true}),
    cache.delete("/api/observations/mesonet"),
    cache.delete("/api/observations/rolling"),
  ])).catch(()=>{});
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
        // The table endpoint sets no-store itself, and default mode can reuse its HTML preload.
        const response=await fetch(url,{cache:url===observations?"default":"no-store"}),data=await response.json();
        if(!response.ok)throw Error(data.error||"Prepared weather data unavailable.");
        const stamp=Date.now();memory.set(url,{data,stamp});remember(url,data,stamp);
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
      const cache=await disk();
      const previousUrl=url===observations?"/api/observations/hourly":url===metarLoop?"/api/station-plots":null;
      const response=await cache?.match(url)||(previousUrl?await cache?.match(previousUrl):null);
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
  async function prime(){
    // Do not put these small manifests behind the larger METAR map request.
    const imagery=Promise.allSettled([radarManifest,satelliteManifest].map(url=>read(url,{force:true})));
    for(const url of ["/api/forecast","/api/air-quality"])read(url).catch(()=>{});
    await imagery;
    read(metarLoop).catch(()=>{});
  }
  function warmLatest(){
    const connection=window.navigator?.connection;
    if(document.hidden||connection?.saveData||["slow-2g","2g"].includes(connection?.effectiveType))return;
    const radarData=memory.get(radarManifest)?.data;
    const satelliteData=memory.get(satelliteManifest)?.data;
    const radarFrame=radarData?.frames?.at(-1),satelliteFrame=satelliteData?.frames?.at(-1);
    if(radarFrame)radar(radarFrame,radarData).catch(()=>{});
    if(satelliteFrame)image(satelliteFrame.url).catch(()=>{});
  }
  return {read,subscribe,prime,warmLatest,radar,image};
})();
