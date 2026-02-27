import { parseYaml } from 'obsidian';

export function normalizeYamlValue(v: any): any {
  if (v == null) return null;
  if (typeof v !== 'string') return v;
  const s = v.trim();
  if (!s) return null;
  if ((s.startsWith('[') && s.endsWith(']')) || (s.startsWith('{') && s.endsWith('}'))) {
    try {
      return JSON.parse(s);
    } catch {
      return s;
    }
  }
  return s;
}

export function extractFrontmatter(md: string): { fm: Record<string, any> | null; body: string } {
  const text = String(md ?? '');
  if (!text.startsWith('---\n')) return { fm: null, body: text };
  const end = text.indexOf('\n---', 4);
  if (end === -1) return { fm: null, body: text };
  const raw = text.slice(4, end + 1);
  const body = text.slice(end + 4);
  try {
    const fm = parseYaml(raw) as any;
    if (fm && typeof fm === 'object') return { fm: fm as Record<string, any>, body };
  } catch {
    // ignore
  }
  return { fm: null, body: text };
}

export function buildPeekPrelude(fm: Record<string, any> | null): string {
  if (!fm) return '';
  const lines: string[] = [];

  const pick = (k: string): string => {
    const v = (fm as any)[k];
    if (v == null) return '';
    const s = String(v).trim();
    return s;
  };

  const cover = pick('cover');
  const video = pick('video');
  const caption = pick('caption');
  const videoUrl = pick('video_url');
  const authorUrl = pick('author_url');

  if (!cover && !video && !caption && !videoUrl && !authorUrl) return '';

  lines.push('## Preview');
  lines.push('');

  if (cover) {
    lines.push('**Cover**');
    lines.push(`![[${cover}]]`);
    lines.push('');
  }

  if (video) {
    lines.push('**Video**');
    lines.push(`![[${video}]]`);
    lines.push('');
  }

  if (caption) {
    lines.push('**Caption**');
    lines.push(caption);
    lines.push('');
  }

  const links: string[] = [];
  if (videoUrl) links.push(`- video_url: ${videoUrl}`);
  if (authorUrl) links.push(`- author_url: ${authorUrl}`);
  if (links.length) {
    lines.push('**Links**');
    lines.push(...links);
    lines.push('');
  }

  lines.push('---');
  lines.push('');
  return lines.join('\n');
}
