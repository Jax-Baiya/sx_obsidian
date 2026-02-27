export const DEFAULT_LIBRARY_COLUMNS: Record<string, boolean> = {
  index: true,
  thumb: true,
  id: true,
  author: true,
  bookmarked: true,
  status: true,
  rating: true,
  tags: true,
  notes: true,
  product_link: false,
  author_links: false,
  platform_targets: false,
  post_url: false,
  published_time: false,
  workflow_log: false,
  actions: true
};

export const DEFAULT_LIBRARY_COLUMN_ORDER: string[] = [
  'index',
  'thumb',
  'id',
  'author',
  'bookmarked',
  'status',
  'rating',
  'tags',
  'notes',
  'product_link',
  'author_links',
  'platform_targets',
  'post_url',
  'published_time',
  'workflow_log',
  'actions'
];
