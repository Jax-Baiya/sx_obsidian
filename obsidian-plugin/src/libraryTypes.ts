export type ApiItem = {
  id: string;
  author_id?: string;
  author_unique_id?: string;
  author_name?: string;
  caption?: string;
  bookmarked?: number;
  cover_path?: string;
  video_path?: string;
  updated_at?: string;
  meta?: {
    rating?: number | null;
    status?: string | null;
    statuses?: string[] | null;
    tags?: string | null;
    notes?: string | null;
    product_link?: string | null;
    author_links?: string[] | string | null;
    platform_targets?: string | null;
    workflow_log?: string | null;
    post_url?: string | null;
    published_time?: string | null;
    updated_at?: string | null;
  };
};

export type ApiAuthor = {
  author_id?: string | null;
  author_unique_id: string;
  author_name?: string | null;
  items_count: number;
  bookmarked_count: number;
};

export type ApiNote = {
  id: string;
  bookmarked: boolean;
  author_unique_id?: string | null;
  author_name?: string | null;
  markdown: string;
};
