import { parseYaml } from 'obsidian';

export function tryGetFrontmatter(md: string): any | null {
  const text = String(md ?? '');
  if (!text.startsWith('---')) return null;
  const parts = text.split('---');
  if (parts.length < 3) return null;
  const raw = parts[1];
  try {
    return parseYaml(raw);
  } catch {
    return null;
  }
}

function toStringOrNull(v: any): string | null {
  if (v == null) return null;
  const s = String(v).trim();
  return s ? s : null;
}

function toJsonOrStringOrNull(v: any): string | null {
  if (v == null) return null;
  if (Array.isArray(v) || (typeof v === 'object' && v)) {
    try {
      return JSON.stringify(v);
    } catch {
      return null;
    }
  }
  return toStringOrNull(v);
}

function toStringArrayOrNull(v: any): string[] | null {
  if (v == null) return null;
  if (Array.isArray(v)) {
    const arr = v.map((x: any) => String(x).trim()).filter(Boolean);
    return arr.length ? arr : [];
  }

  const s = String(v).trim();
  if (!s) return null;

  if ((s.startsWith('[') && s.endsWith(']')) || (s.startsWith('{') && s.endsWith('}'))) {
    try {
      const obj = JSON.parse(s);
      if (Array.isArray(obj)) {
        const arr = obj.map((x: any) => String(x).trim()).filter(Boolean);
        return arr.length ? arr : [];
      }
    } catch {
      // fall through to csv/newline split
    }
  }

  const arr = s
    .split(/[\n,]/g)
    .map((x) => String(x).trim())
    .filter(Boolean);
  return arr.length ? arr : [];
}

export function extractUserMetaPayload(md: string): any | null {
  const fm = tryGetFrontmatter(md);
  if (!fm || typeof fm !== 'object') return null;

  const tagsVal = (fm as any).tags;
  const tagsStr = Array.isArray(tagsVal)
    ? tagsVal.map((t: any) => String(t).trim()).filter(Boolean).join(',')
    : toStringOrNull(tagsVal);

  return {
    rating: (fm as any).rating != null && String((fm as any).rating).trim() !== '' ? Number((fm as any).rating) : null,
    status: (() => {
      const s = (fm as any).status;
      if (Array.isArray(s)) {
        const first = s.map((x: any) => String(x).trim()).filter(Boolean)[0];
        return first ? String(first) : null;
      }
      return toStringOrNull(s);
    })(),
    statuses: (() => {
      const s = (fm as any).status;
      if (Array.isArray(s)) {
        const arr = s.map((x: any) => String(x).trim()).filter(Boolean);
        return arr.length ? arr : null;
      }
      const one = toStringOrNull(s);
      return one ? [one] : null;
    })(),
    tags: tagsStr,
    notes: toStringOrNull((fm as any).notes),
    product_link: toStringOrNull((fm as any).product_link),
    author_links: toStringArrayOrNull((fm as any).author_links),
    platform_targets: toJsonOrStringOrNull((fm as any).platform_targets ?? (fm as any).platform_target),
    workflow_log: toJsonOrStringOrNull((fm as any).workflow_log),
    post_url: toStringOrNull((fm as any).post_url),
    published_time: toStringOrNull((fm as any).published_time)
  };
}

export function extractIdFromFrontmatter(md: string, fallback: string): string {
  const fm = tryGetFrontmatter(md);
  if (!fm || typeof fm !== 'object') return String(fallback || '').trim();
  const id = String((fm as any)?.id || '').trim();
  return id || String(fallback || '').trim();
}

export function isMediaMissing(md: string): boolean {
  const fm = tryGetFrontmatter(md);
  if (!fm || typeof fm !== 'object') return false;
  const v = (fm as any).media_missing;
  return v === true || v === 'true' || v === 1 || v === '1';
}
