"use strict";
// Transparent, label-free Census primary/secondary roads, above the radar.
window.WeatherRadarRoads = (() => {
  const endpoint="https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/export";
  function roadStyle(id,width) {
    return {id,source:{type:"mapLayer",mapLayerId:id},drawingInfo:{showLabels:false,
      labelingInfo:[],renderer:{type:"simple",symbol:{type:"esriSLS",
        style:"esriSLSSolid",color:[100,110,118,255],width}}}};
  }
  function addTo(map,onError) {
    map.createPane("roads");
    const pane=map.getPane("roads");pane.style.zIndex=390;pane.style.pointerEvents="none";
    const Roads=L.TileLayer.extend({
      getTileUrl(coords) {
        const half=20037508.342789244,span=2*half/2**coords.z;
        const left=-half+coords.x*span,top=half-coords.y*span;
        // Census supplies different generalizations at different map scales.
        // Its published scale limits still apply to dynamic-layer requests.
        const dpi=coords.z<7?24:96,z=coords.z+(coords.z<7?2:0);
        const primary=z<8?0:z<10?1:2;
        const secondary=z<8?null:z<10?3:z<11?4:z<13?5:6;
        const layers=[roadStyle(primary,.8*(96/dpi))];
        if(secondary!=null)layers.push(roadStyle(secondary,.55*(96/dpi)));
        const params=new URLSearchParams({f:"image",format:"png32",transparent:"true",
          bbox:[left,top-span,left+span,top].join(","),bboxSR:"3857",imageSR:"3857",
          size:"256,256",dpi:String(dpi),layers:`show:${layers.map(l=>l.id).join(",")}`,dynamicLayers:JSON.stringify(layers)});
        return `${endpoint}?${params}`;
      }
    });
    const roads=new Roads(endpoint,{pane:"roads",opacity:.3,tileSize:256,
      minZoom:5,maxZoom:13,noWrap:true,updateWhenIdle:true,keepBuffer:1,
      attribution:'Roads: <a href="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html">U.S. Census Bureau</a>'});
    if(onError)roads.on("tileerror",onError);
    return roads.addTo(map);
  }
  return {addTo};
})();
