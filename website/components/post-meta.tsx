import { formatDate } from '@/lib/blog';

/** A post's date, author and tags: one quiet line under its title or description. */
export function PostMeta({ date, author, tags }: { date: string; author?: string; tags: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted-foreground">
      <time dateTime={date}>{formatDate(date)}</time>
      {author ? <span>{author}</span> : null}
      {tags.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Tags">
          {tags.map((tag) => (
            <li key={tag} className="rounded-md border px-1.5 py-0.5 text-xs leading-none text-muted-foreground">
              {tag}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
