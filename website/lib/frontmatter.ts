import { z } from 'zod';

/**
 * A page's meta description, checked when the site builds for every guide and post. Google
 * shows about 155 characters: a shorter one wastes the snippet, a longer one is cut short.
 */
export const searchDescription = z.string().min(120).max(160);
