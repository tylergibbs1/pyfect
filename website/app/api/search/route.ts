import { source } from '@/lib/source';
import { createFromSource } from 'fumadocs-core/search/server';

// Built once at build time and served as a static file (see components/search.tsx).
export const revalidate = false;
export const { staticGET: GET } = createFromSource(source);
