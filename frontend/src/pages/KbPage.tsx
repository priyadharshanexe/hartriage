import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import { Link, useParams } from "react-router-dom";
import { Badge, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import type { KbItem } from "../lib/types";

export function KbIndexPage() {
  const index = useQuery({ queryKey: ["kb"], queryFn: () => api<{ items: KbItem[] }>("/v1/kb") });
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Knowledge base" description="One article per rule, for the agent working the ticket." />
      {index.isPending ? (
        <LoadingState />
      ) : index.isError ? (
        <ErrorState error={index.error} />
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
          {index.data.items.map((item) => (
            <li key={item.slug} className="px-4 py-3">
              <Link to={`/kb/${item.slug}`} className="font-medium text-brand-700 hover:underline">
                {item.rule_id && <Badge>{item.rule_id}</Badge>} {item.title}
              </Link>
              <p className="text-sm text-slate-600">{item.summary}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function KbPage() {
  const { slug = "" } = useParams();
  const article = useQuery({ queryKey: ["kb", slug], queryFn: () => api<string>(`/v1/kb/${slug}`, { text: true }) });
  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/kb" className="text-sm text-brand-700">
        ← All articles
      </Link>
      <article className="prose-kb mt-4 rounded-lg border border-slate-200 bg-white p-6">
        {article.isPending ? (
          <LoadingState />
        ) : article.isError ? (
          <ErrorState error={article.error} />
        ) : (
          <Markdown
            components={{
              // Links between articles stay inside the app.
              a: ({ href, children }) =>
                href && /^[A-Za-z0-9-]+\.md$/.test(href) ? <Link to={`/kb/${href.replace(/\.md$/, "")}`}>{children}</Link> : <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>,
            }}
          >
            {article.data}
          </Markdown>
        )}
      </article>
    </div>
  );
}
