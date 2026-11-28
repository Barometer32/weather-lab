'use strict';
// Small Leaflet harness with geographic projection and prepared-feed callbacks.
const fs=require('node:fs'),vm=require('node:vm');
module.exports=function viewer(data,{width=375,height=560,zoom=9,center=[44.945,-93.343],codePath='static/metar-views.js'}={}){
 const nodes=new Map(),shown=new Map(),subscribers=new Map(),events={},reads=[];
 const element=()=>({value:'',hidden:false,children:[],events:{},style:{setProperty(){}},setAttribute(k,v){this[k]=v;},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const project=(lat,lon,z)=>{const world=256*2**z,s=Math.sin(lat*Math.PI/180);return{x:(lon+180)/360*world,y:(.5-Math.log((1+s)/(1-s))/(4*Math.PI))*world};};
 const point=([lat,lon])=>{const p=project(lat,lon,zoom),c=project(...center,zoom);return{x:p.x-c.x+width/2,y:p.y-c.y+height/2};};
 const map={setView(){return this;},fitBounds(){return this;},getSize(){return{x:width,y:height};},latLngToContainerPoint:point,on(k,f){events[k]=f;},invalidateSize(){}};
 const context={window:{WeatherPrepared:{async read(url){reads.push(url);if(url!=='/api/station-plots?view=loop')throw Error('Unexpected feed: '+url);return data;},subscribe(url,fn){if(!subscribers.has(url))subscribers.set(url,[]);subscribers.get(url).push(fn);}},WeatherFullscreen:{attach(){}},addEventListener(){}},document:{getElementById:get,createElement:element,hidden:false},Intl,Math,Number,Date,Map,Set,WeakMap,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(m){shown.delete(m.title.split(' · ')[0]);}}),divIcon:x=>x,marker:(position,opts)=>({position,...opts,bindPopup(value){this.popup=value;return this;},addTo(){shown.set(this.title.split(' · ')[0],this);return this;},setIcon(v){this.icon=v;return this;},setLatLng(v){this.position=v;return this;},setPopupContent(value){this.popup=value;return this;}})}};
 for(const path of ['static/metar-model.js',codePath])vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
 const flush=()=>new Promise(setImmediate);
 return {get,reads,marker:id=>shown.get(id),ids:()=>[...shown.keys()].sort(),
  async load(){context.window.WeatherMetars.select('metar');await flush();},
  async mode(value){context.window.WeatherMetars.select(value);await flush();},
  frame(value){get('metar-timeline').events.input({target:{value:String(value)}});},
  zoom(value){zoom=value;events.moveend();},
  snapshot(){return [...shown].sort(([a],[b])=>a.localeCompare(b)).map(([id,m])=>({id,position:Array.from(m.position),icon:m.icon,popup:m.popup.children.map(n=>n.textContent)}));},
  adoptMap(next){data=next;for(const f of subscribers.get('/api/station-plots?view=loop')||[])f(next);},
  async refresh(){get('refresh-metar').events.click();await flush();}
 };
};
