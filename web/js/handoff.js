// How the next building is being opened: from the office-to-housing map (the map stays on screen until the 3-D view
// is drawn, then they cross-fade) or anywhere else (the 3-D view replaces the page as before).
// metresPerPixel: the map's scale at hand-over; the 3-D view opens straight down at the same scale.
export const handoff = { from: null, zoomX: null, zoomY: null, metresPerPixel: null, mapWidth: null, mapHeight: null };
