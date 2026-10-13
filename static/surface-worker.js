"use strict";
importScripts("/static/surface-core.js");
self.onmessage=event=>{
  try{
    const result=SurfaceCore.analyze(event.data);
    self.postMessage(result,[result.values.buffer,result.u.buffer,result.v.buffer,result.support.buffer]);
  }catch(error){self.postMessage({id:event.data.id,error:error.message});}
};
