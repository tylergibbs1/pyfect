import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="flex flex-col justify-center items-center text-center flex-1 px-4 py-16">
      <h1 className="text-4xl font-bold mb-4">pyfect</h1>
      <p className="text-fd-muted-foreground max-w-xl mb-8">
        Effect for Python: typed errors and services, a fiber runtime with structured
        concurrency, layers, schedules, streams and observability. Fully inferred by pyright.
      </p>
      <div className="flex flex-wrap gap-3 justify-center">
        <Link
          href="/docs"
          className="rounded-lg bg-fd-primary px-4 py-2 font-medium text-fd-primary-foreground"
        >
          Read the guide
        </Link>
        <Link href="/docs/reference" className="rounded-lg border px-4 py-2 font-medium">
          API reference
        </Link>
      </div>
    </main>
  );
}
