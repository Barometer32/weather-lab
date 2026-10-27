"use strict";
importScripts("/static/radar-renderer.js?v=map-motion-v1");
let grid;
self.onmessage=event=>{
  const request=event.data,iterator=WeatherRadarRenderer.render(request,grid);
  let result;do {result=iterator.next();}while(!result.done);
  grid=result.value.grid;
  const {id,width,height,zoom,topLeft}=request,pixels=result.value.pixels;
  self.postMessage({id,width,height,zoom,topLeft,pixels},[pixels.buffer]);
};
