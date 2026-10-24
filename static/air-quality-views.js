"use strict";
// Fixed, archived regional graphics. Visitors never contact the upstream feeds.
window.WeatherAirQuality = (() => {
  const el=id=>document.getElementById(id);
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const images=new Map();let data,index=0,followLatest=true,busy=false,serial=0;
  async function imageReady(url){
    if(!images.has(url)){
      const picture=new Image();picture.src=url;
      images.set(url,picture.decode().then(()=>picture).catch(error=>{images.delete(url);throw error;}));
    }
    return images.get(url);
  }
  async function showFrame(n){
    const frames=data.frames,next=Math.max(0,Math.min(n,frames.length-1)),frame=frames[next],request=++serial;
    try{
      const image=await imageReady(frame.url);if(request!==serial)return;
      index=next;el("air-quality-map").src=image.src;el("air-quality-map").hidden=false;
      el("air-quality-map").alt=`Regional air quality captured ${time.format(new Date(frame.time))}`;
      el("airq-time").textContent=`${time.format(new Date(frame.time))} · ${index+1}/${frames.length}`;
      const slider=el("airq-timeline");slider.max=String(frames.length-1);slider.value=String(index);slider.disabled=frames.length<2;
      slider.setAttribute("aria-valuetext",el("airq-time").textContent);
      slider.style.setProperty("--progress",`${frames.length>1?100*index/(frames.length-1):0}%`);
      el("airq-status").textContent=`${frames.length}/12 hourly snapshots${frames.length<12?" · History is building":""} · AirNow data as of ${time.format(new Date(frame.sourceTime))}${data.stale?" · Background capture delayed":""}`;
    }catch(error){if(request===serial)el("airq-status").textContent="This Air Q snapshot could not load. The previous image is retained.";}
  }
  async function load(){
    if(busy)return;busy=true;el("refresh-air-quality").disabled=true;
    try{
      const response=await fetch("/api/air-quality",{cache:"no-store"}),next=await response.json();
      if(!response.ok)throw Error(next.error||"Air Q history unavailable");
      if(!next.frames?.length)throw Error("Air Q history is building; no snapshots are ready yet.");
      const selected=data?.frames[index]?.time;data=next;
      const restored=!followLatest&&selected?data.frames.findIndex(f=>f.time===selected):-1;
      await showFrame(restored>=0?restored:followLatest?data.frames.length-1:0);
      const keep=new Set(data.frames.map(f=>f.url));for(const url of images.keys())if(!keep.has(url))images.delete(url);
    }catch(error){el("airq-status").textContent=error.message+(data?" Previous snapshots retained; check the displayed time.":"");}
    finally{busy=false;el("refresh-air-quality").disabled=false;}
  }
  el("refresh-air-quality").addEventListener("click",load);
  el("airq-timeline").addEventListener("input",event=>{
    if(!data)return;const n=Number(event.target.value);followLatest=n===data.frames.length-1;showFrame(n);
  });
  setInterval(()=>{if(!document.hidden&&!el("air-quality").hidden)load();},60000);
  return {select(id){if(id==="air-quality")load();}};
})();
