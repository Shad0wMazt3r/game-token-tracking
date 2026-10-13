/** Pure protocol and geometry checks, independent of Foundry globals. */
export function validatePacket(packet, sceneId) {
  if (!packet || packet.protocol !== 1 || packet.scene_id !== sceneId ||
      typeof packet.session !== "string" || !packet.session ||
      !Number.isSafeInteger(packet.sequence) || packet.sequence < 0 ||
      !Number.isSafeInteger(packet.columns) || packet.columns < 1 ||
      !Number.isSafeInteger(packet.rows) || packet.rows < 1 ||
      !Array.isArray(packet.events) || packet.events.length > 64) {
    throw new Error("Bridge protocol, scene, or grid mismatch");
  }
  for (const event of packet.events) {
    if (!event || typeof event.piece_id !== "string" || !event.piece_id ||
        !Number.isSafeInteger(event.sequence) || event.sequence < 1 || event.sequence > packet.sequence ||
        !Number.isSafeInteger(event.column) || event.column < 0 || event.column >= packet.columns ||
        !Number.isSafeInteger(event.row) || event.row < 0 || event.row >= packet.rows) {
      throw new Error("Invalid movement event");
    }
  }
  return packet;
}

export function tokenPosition(event, packet, geometry, token) {
  const {size, originX, originY, sceneX, sceneY, sceneWidth, sceneHeight} = geometry;
  if (![size,originX,originY,sceneX,sceneY,sceneWidth,sceneHeight,token.width,token.height].every(Number.isFinite) ||
      size <= 0 || token.width <= 0 || token.height <= 0) throw new Error("Invalid scene geometry");
  // MVP: cell indicates the top-left square of the token footprint.
  const x = originX + event.column*size;
  const y = originY + event.row*size;
  if (originX < sceneX || originY < sceneY ||
      originX+packet.columns*size > sceneX+sceneWidth || originY+packet.rows*size > sceneY+sceneHeight ||
      x+token.width*size > sceneX+sceneWidth || y+token.height*size > sceneY+sceneHeight) {
    throw new Error("Physical board or token footprint is outside the scene");
  }
  return {x,y};
}

export function loopbackURL(value) {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["localhost","127.0.0.1"].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash || !["","/"].includes(url.pathname)) {
    throw new Error("Use an HTTP localhost bridge URL");
  }
  return url.origin;
}
