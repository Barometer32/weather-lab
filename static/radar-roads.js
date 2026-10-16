/* Unlabeled Census highway geometry; no map keys or external tile requests. */
(function(root) {
  "use strict";
  root.WeatherRadarRoads = {
    async addTo(map) {
      const pane = map.createPane("radar-roads");
      pane.style.zIndex = 390; // above echoes, below state/county boundaries
      pane.style.pointerEvents = "none";
      const response = await fetch("/static/radar-highways.geojson");
      if (!response.ok) throw new Error("Highway reference could not load");
      const data = await response.json();
      const renderer = L.canvas({pane:"radar-roads", padding:0.3});
      const style = feature => {
        const type = feature.properties.class, zoom = map.getZoom();
        return {color:"#59616b", weight:type === "I" ? 0.9 : 0.65,
          opacity:type === "I" ? 0.32 : type === "U" ? 0.22 : zoom >= 9 ? 0.15 : 0,
          fill:false, interactive:false, pane:"radar-roads", renderer};
      };
      const roads = L.geoJSON(data, {style, interactive:false, pane:"radar-roads", renderer}).addTo(map);
      map.on("zoomend", () => roads.setStyle(style));
      map.attributionControl.addAttribution('Highways: <a href="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html">U.S. Census Bureau</a>');
      return roads;
    }
  };
})(window);
