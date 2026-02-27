export function positionFloatingVideo(anchorEl: HTMLElement, video: HTMLVideoElement, w: number, h: number): void {
  const rect = anchorEl.getBoundingClientRect();

  let x = Math.floor(rect.right + 10);
  let y = Math.floor(rect.top);
  if (x + w > window.innerWidth - 8) x = Math.max(8, Math.floor(rect.left - w - 10));
  if (y + h > window.innerHeight - 8) y = Math.max(8, window.innerHeight - h - 8);
  if (y < 8) y = 8;

  video.style.left = `${x}px`;
  video.style.top = `${y}px`;
  video.style.width = `${Math.floor(w)}px`;
  video.style.height = `${Math.floor(h)}px`;
}
