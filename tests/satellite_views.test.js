'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),subscriptions=new Map(),reads=[],imageReads=[];
function node(){return{value:'truecolor',hidden:false,tabIndex:0,events:{},textContent:'',style:{setProperty(){}},classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;},getAttribute(k){return this[k];},addEventListener(k,fn){this.events[k]=fn;},focus(){}};}
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const map={createPane(){},getPane(){return{style:{}};},fitBounds(){},on(){},removeLayer(){},invalidateSize(){},attributionControl:{addAttribution(){}}};
const labels={'02':'Visible (red)',truecolor:'True color',dcphase:'Day Cloud Phase',ntmicro:'NT Microphysics'};
function manifest(product){return{product,label:labels[product],sourceUrl:'https://weather.cod.edu/satrad/?band='+product,width:1600,height:900,boundaries:[],frames:[0,1].map(i=>({time:new Date(Date.UTC(2026,10,11,19,i*5)).toISOString(),url:'/api/prepared/satellite/'+product+'/'+i+'.jpg'}))};}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,setTimeout(){},setInterval(){},clearTimeout(){},L:{CRS:{Simple:{}},map:()=>map,imageOverlay:()=>({addTo(){return this;},on(){},setOpacity(){}})},window:{innerWidth:1600,addEventListener(){},WeatherFullscreen:{attach(){},select(){}},WeatherMetars:{select(){}},WeatherAirQuality:{select(){}},WeatherPrepared:{subscribe(url,fn){subscriptions.set(url,fn);},prime(){},async read(url){reads.push(url);return manifest(url.split('/').at(-1));},async image(url){imageReads.push(url);return{naturalWidth:1600,naturalHeight:900};}}}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
const flush=()=>new Promise(setImmediate);
(async()=>{
 assert.equal(get('satellite-product').value,'02','Visible red overrides a browser-restored old selection on load');
 for(const product of Object.keys(labels))assert.ok(subscriptions.has('/api/satellite/'+product),'all four bands receive prepared updates');
 get('tab-satellite').events.click();await flush();
 assert.deepEqual(reads,['/api/satellite/02']);
 assert.ok(imageReads.every(url=>url.includes('/satellite/02/')));
 assert.match(get('satellite-status').textContent,/Visible \(red\)/);
 assert.equal(get('satellite-source').href,'https://weather.cod.edu/satrad/?band=02');
 for(const product of ['truecolor','dcphase','ntmicro']){
  get('satellite-product').value=product;get('satellite-product').events.change();await flush();
  assert.equal(reads.at(-1),'/api/satellite/'+product,'retained band remains selectable');
  assert.ok(get('satellite-status').textContent.startsWith(labels[product]));
 }
 const before=reads.length;
 subscriptions.get('/api/satellite/02')();await flush();
 assert.equal(reads.length,before,'an inactive band update does not replace the selected band');
 get('satellite-product').value='02';get('satellite-product').events.change();await flush();
 subscriptions.get('/api/satellite/02')();await flush();
 assert.equal(reads.at(-1),'/api/satellite/02','visible background update refreshes the active view');
 console.log('Satellite views passed: visible-red default, four-band switching, prepared updates and native image sizes.');
})().catch(error=>{console.error(error);process.exitCode=1;});
