"use strict";
window.WeatherAI = (() => {
  const el=id=>document.getElementById(id);
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const names={tempF:"Temperature",dewpointF:"Dew point",wind:"Wind speed and direction"};
  const cache=new Map();
  let data,map,layers,index=0,request=0,loading=false,timer,playing=false,playTimer,generation=0;
  const visible=()=>!document.hidden&&!el("ai-forecast").hidden;
  function node(tag,text){const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;}
  const duration=s=>s<60?`${s} s`:`${Math.floor(s/60)} min ${s%60} s`;
  function reset(){map.fitBounds([[41.4,-102.2],[49.2,-90.2]]);}
  function init(){
    if(map)return;
    map=L.map("ai-map",{minZoom:4,maxZoom:12,zoomSnap:.1,zoomDelta:.1,wheelPxPerZoomLevel:120});reset();
    map.createPane("aiRaster").style.zIndex=250;
    map.createPane("aiBoundaries").style.zIndex=450;
    map.getPane("aiBoundaries").style.pointerEvents="none";
    for(const [kind,opacity] of [["uscounties",.25],["usstates",.9]])
      L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{pane:"aiBoundaries",opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    layers=L.layerGroup().addTo(map);
  }
  function showProgress(training={}){
    el("ai-stage").textContent=training.state==="completed"?"Training complete — experimental model ready":training.message||"Model has not been trained yet";
    const bar=el("ai-progress");bar.value=Math.max(0,Math.min(100,training.percent||0));
    bar.setAttribute("aria-valuetext",`${training.percent||0}% · ${training.stage||"not started"}`);
    const elapsed=Number.isFinite(training.elapsedSeconds)?`Elapsed ${duration(training.elapsedSeconds)}`:"";
    const eta=training.state==="running"&&Number.isFinite(training.estimatedRemainingSeconds)?` · About ${duration(training.estimatedRemainingSeconds)} left in this stage`:training.state==="running"?" · Estimating remaining time…":"";
    el("ai-progress-detail").textContent=`${elapsed}${eta}${training.updatedAt?` · Last update ${time.format(new Date(training.updatedAt))}`:""}`;
    el("ai-events").replaceChildren();
    for(const event of training.events||[])el("ai-events").append(node("li",`${event.percent}% · ${event.message} · ${duration(event.elapsedSeconds)}`));
  }
  function scores(report){
    if(!report)return;
    el("ai-test-period").textContent=`Held-out dates: ${time.format(new Date(report.testStart))} to ${time.format(new Date(report.testEnd))}. ${report.stationCount} airports; ${report.trainingData.days} archive days. Blend weights chosen on earlier validation dates.`;
    const body=el("ai-scores");body.replaceChildren();
    for(const score of report.scores){
      const row=node("tr");row.append(node("th",`+${score.leadHours} h`));
      for(const field of ["tempF","dewpointF","wind"]){
        const f=score.forecast[field],b=score.persistence[field],weight=score.modelWeight[field];
        const cell=node("td",`${f.mae.toFixed(1)} / ${b.mae.toFixed(1)}`);
        cell.append(node("small",`${f.count.toLocaleString()} station-hour cases · ${weight===0?"Unchanged-value fallback":`${Math.round(100*weight)}% model blend`}`));
        row.append(cell);
      }
      body.append(row);
    }
    el("ai-model-description").textContent=`${report.algorithm}. Trained ${time.format(new Date(report.trainedAt))}; model ${report.modelId}. Only the 25-airport network is forecast; maps between airports are estimates. No training job starts from a page visit.`;
    el("ai-limitations").replaceChildren();
    for(const text of report.limitations||[])el("ai-limitations").append(node("li",text));
  }
  function legend(product,field){
    const unit=field==="wind"?"mph":"°F",palette=product.palette,low=palette[0][0],span=palette.at(-1)[0]-low;
    const bar=node("div"),ticks=node("div");bar.className="surface-gradient";ticks.className="surface-ticks";
    const stops=palette.slice(0,-1).flatMap(([v,c],i)=>[`${c} ${100*(v-low)/span}%`,`${c} ${100*(palette[i+1][0]-low)/span}%`]);
    bar.style.background=`linear-gradient(to right,${stops.join(",")})`;
    for(const [v] of palette){
      if(field!=="wind"&&v%10!==0&&v!==palette.at(-1)[0])continue;
      const tick=node("span",String(v));tick.style.left=`${100*(v-low)/span}%`;ticks.append(tick);
    }
    el("ai-legend").replaceChildren();el("ai-legend").append(node("strong",`${names[field]} · ${unit} · 5 ${unit} bands`),bar,ticks);
  }
  async function selectFrame(position){
    const forecast=data?.forecast;
    if(!forecast?.history?.length)return;
    const token=++request;
    index=Math.max(0,Math.min(position,forecast.history.length-1));
    const frame=forecast.history[index],field=el("ai-field").value;
    el("ai-timeline").value=String(index);
    el("ai-timeline").style.setProperty("--progress",`${100*index/(forecast.history.length-1)}%`);
    el("ai-time").textContent=`+${frame.leadHours} hours · ${time.format(new Date(frame.hour))} · FORECAST`;
    el("ai-timeline").setAttribute("aria-valuetext",el("ai-time").textContent);
    init();layers.clearLayers();el("ai-legend").replaceChildren();
    el("ai-map-status").textContent="Loading experimental forecast map…";
    try{
      let manifest=cache.get(frame.analysisUrl);
      if(!manifest){
        if(window.WeatherData)manifest=await window.WeatherData.json(frame.analysisUrl,{maxAge:Infinity});
        else{const response=await fetch(frame.analysisUrl);if(!response.ok)throw Error("Forecast map could not load");manifest=await response.json();}
        if(manifest.hour!==frame.hour||manifest.leadHours!==frame.leadHours)throw Error("Forecast map time mismatch");
        cache.set(frame.analysisUrl,manifest);if(cache.size>10)cache.delete(cache.keys().next().value);
      }
      if(token!==request)return;
      const product=manifest.fields[field];
      L.imageOverlay(product.imageUrl,manifest.bounds,{pane:"aiRaster",opacity:1,interactive:false}).on("error",()=>{
        if(token===request)el("ai-map-status").textContent="The forecast image could not load. Try Refresh status.";
      }).addTo(layers);
      L.geoJSON(product.contours,{style:{color:"#233940",weight:.8,opacity:.65},onEachFeature:(feature,line)=>{
        line.bindTooltip(String(feature.properties.value),{sticky:true});
      }}).addTo(layers);
      for(const arrow of product.arrows||[]){
        const icon=L.divIcon({className:"surface-wind",iconSize:[28,28],iconAnchor:[14,14],html:`<svg width="28" height="28" viewBox="-14 -14 28 28" aria-hidden="true"><g transform="rotate(${(arrow.direction+180)%360})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M0 10V-10M-3 -6L0 -11L3 -6" stroke="white" stroke-width="3.5"/><path d="M0 10V-10M-3 -6L0 -11L3 -6" stroke="#203540" stroke-width="1.5"/></g></svg>`});
        L.marker([arrow.lat,arrow.lon],{icon,interactive:false,keyboard:false}).addTo(layers);
      }
      legend(product,field);
      const score=forecast.modelReport.scores.find(s=>s.leadHours===frame.leadHours),weight=score?.modelWeight[field];
      el("ai-map-status").textContent=`${product.used} airport predictions · ${weight===0?"Unchanged-value fallback selected by validation":`Experimental ${Math.round(100*(weight??1))}% model blend`} · ${forecast.stale?"Input update delayed; showing saved forecast":"Coarse station-based estimates; not observed conditions"}`;
      setTimeout(()=>map.invalidateSize(),0);
    }catch(error){if(token===request)el("ai-map-status").textContent=error.message;}
  }
  function stop(){playing=false;generation++;clearTimeout(playTimer);el("ai-play").textContent="Play";el("ai-play").setAttribute("aria-pressed","false");}
  async function tick(version){
    if(!playing||version!==generation)return;
    if(!visible()){stop();return;}
    await selectFrame((index+1)%data.forecast.history.length);
    if(playing&&version===generation)playTimer=setTimeout(()=>tick(version),1400);
  }
  function schedule(){
    clearTimeout(timer);
    if(visible())timer=setTimeout(load,data?.training?.state==="running"||!data?.forecast?5000:60000);
  }
  async function load(){
    if(loading)return;loading=true;el("refresh-ai").disabled=true;
    try{
      const response=await fetch("/api/ai-forecast",{cache:"no-store"});if(!response.ok)throw Error("Forecast status unavailable");
      const fresh=await response.json(),previous=data;data=fresh;
      showProgress(fresh.training);scores(fresh.model);
      const forecast=fresh.forecast;
      if(forecast?.history?.length){
        el("ai-timeline").max=String(forecast.history.length-1);el("ai-timeline").disabled=false;el("ai-play").disabled=false;
        const issue=time.format(new Date(forecast.issueHour)),latest=forecast.latestReportTime?time.format(new Date(forecast.latestReportTime)):"unknown";
        el("ai-source-status").textContent=`Reference hourly analysis ${issue} · latest input report ${latest}. Official airport inputs only; no radar, satellite or upper-air data.${forecast.stale?" Input update delayed.":""}${fresh.preparation?.state==="failed"?" New forecast preparation failed; previous maps retained.":""}`;
        if(!previous?.forecast||previous.forecast.inputSignature!==forecast.inputSignature||previous.forecast.modelId!==forecast.modelId)await selectFrame(index);
      }else{
        el("ai-map-status").textContent=fresh.preparation?.message||"Model ready. Forecast maps prepare during the hourly METAR collection; deployment triggers that collection.";
      }
    }catch(error){el("ai-map-status").textContent=error.message;}
    finally{loading=false;el("refresh-ai").disabled=false;schedule();}
  }
  function select(id){
    if(id!=="ai-forecast"){stop();clearTimeout(timer);return;}
    init();load();setTimeout(()=>map.invalidateSize(),0);
  }
  el("refresh-ai").addEventListener("click",load);
  el("ai-field").addEventListener("change",()=>selectFrame(index));
  el("ai-timeline").addEventListener("input",event=>{stop();selectFrame(Number(event.target.value));});
  el("ai-reset").addEventListener("click",()=>{init();reset();});
  el("ai-play").addEventListener("click",()=>{if(playing){stop();return;}playing=true;el("ai-play").textContent="Pause";el("ai-play").setAttribute("aria-pressed","true");tick(generation);});
  document.addEventListener("visibilitychange",()=>{if(!visible()){stop();clearTimeout(timer);}else load();});
  return {select};
})();
