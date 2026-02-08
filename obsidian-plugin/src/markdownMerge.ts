import { parseYaml, stringifyYaml } from 'obsidian';

// Keep in sync with backend renderer markers.
const MANAGED_START = '<!-- sx-managed:start -->';
const MANAGED_END = '<!-- sx-managed:end -->';

// User section markers (plugin-managed).
const USER_START = '<!-- sx-user:start -->';
const USER_END = '<!-- sx-user:end -->';

// Fields users commonly edit directly in YAML/frontmatter.
// (The DB also stores some of these in user_meta; this is an additional safety net.)
const USER_OWNED_KEYS = new Set<string>([
  'status',
  'rating',
  'tags',
  'notes',
  'scheduled_time',
  'product_link',
  'platform_targets',
  'workflow_log',
  'post_url',
  'published_time',
  'sx_select'
]);

function extractFrontmatter(md: string): { fm: any; body: string } {
  const text = String(md ?? '');
  if (!text.startsWith('---')) {
    return { fm: null, body: text };
  }

  // Find the second --- on its own line.
  // We keep this simple and robust for our generated notes.
  const idx = text.indexOf('\n---', 3);
  if (idx === -1) {
    return { fm: null, body: text };
  }

  const rawFm = text.slice(3, idx + 1); // includes leading newline before closing ---
  const body = text.slice(idx + '\n---'.length);

  let fm: any = null;
  try {
    fm = parseYaml(rawFm);
  } catch {
    fm = null;
  }
  return { fm, body: body.replace(/^\n+/, '') };
}

function removeUserSection(body: string): string {
  const b = String(body ?? '');
  const s = b.indexOf(USER_START);
  if (s === -1) return b;
  const e = b.indexOf(USER_END, s);
  if (e === -1) return b;
  return (b.slice(0, s) + b.slice(e + USER_END.length)).trimEnd() + '\n';
}

function extractUserSection(body: string): string {
  const b = String(body ?? '');
  const s = b.indexOf(USER_START);
  if (s !== -1) {
    const e = b.indexOf(USER_END, s);
    if (e !== -1) {
      return b.slice(s + USER_START.length, e).trim();
    }
  }

  // No explicit user section. Try to preserve any user text outside the managed block.
  const ms = b.indexOf(MANAGED_START);
  const me = ms === -1 ? -1 : b.indexOf(MANAGED_END, ms);
  if (ms !== -1 && me !== -1) {
    const before = b.slice(0, ms).trim();
    const after = b.slice(me + MANAGED_END.length).trim();
    const combined = [before, after].filter(Boolean).join('\n\n').trim();
    return combined;
  }

  // If no managed markers exist, treat entire body as user content.
  return b.trim();
}

function isMeaningful(v: any): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'string') return v.trim().length > 0;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

export function mergeMarkdownPreservingUserEdits(existingMd: string, incomingMd: string): string {
  const existing = extractFrontmatter(existingMd);
  const incoming = extractFrontmatter(incomingMd);

  const inFm = (incoming.fm && typeof incoming.fm === 'object') ? incoming.fm : {};
  const exFm = (existing.fm && typeof existing.fm === 'object') ? existing.fm : {};

  // Start with the incoming (template/DB) frontmatter.
  const mergedFm: any = { ...inFm };

  // Preserve all unknown keys from the existing note.
  for (const [k, v] of Object.entries(exFm)) {
    if (!(k in mergedFm)) mergedFm[k] = v;
  }

  // Preserve user-owned keys with preference to existing values.
  for (const k of USER_OWNED_KEYS) {
    if (k in exFm && isMeaningful((exFm as any)[k])) {
      mergedFm[k] = (exFm as any)[k];
    }
  }

  // Body merge: keep the incoming managed block, and append preserved user section.
  let newBody = removeUserSection(incoming.body);
  const userText = extractUserSection(existing.body);

  if (userText) {
    newBody = (newBody.trimEnd() + '\n\n' + USER_START + '\n' + userText + '\n' + USER_END + '\n');
  } else {
    newBody = newBody.trimEnd() + '\n';
  }

  const fmText = stringifyYaml(mergedFm);
  return `---\n${fmText}---\n\n${newBody}`;
}
