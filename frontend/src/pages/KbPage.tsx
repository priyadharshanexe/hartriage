import { useQuery } from "@tanstack/react-query";
import { motion, useScroll, useSpring } from "motion/react";
import { createPortal } from "react-dom";
import { Scramble } from "../components/fx";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link, useParams } from "react-router-dom";
import { ErrorState, LoadingState, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import type { KbItem } from "../lib/types";

export function KbIndexPage() {
  const index = useQuery({ queryKey: ["kb"], queryFn: () => api<{ items: KbItem[] }>("/v1/kb") });
  return (
    <div className="max-w-4xl">
      <PageHeader title="Knowledge base" description="One article per rule, for the agent working the ticket." />
      {index.isPending ? (
        <LoadingState />
      ) : index.isError ? (
        <ErrorState error={index.error} onRetry={() => void index.refetch()} />
      ) : (
        <ul>
          {index.data.items.map((item, i) => (
            <li key={item.slug} className="animate-rise border-b border-rule" style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
              <Link to={`/kb/${item.slug}`} className="group grid gap-x-6 gap-y-1 py-4 sm:grid-cols-[4rem_minmax(0,1fr)]">
                <span className="font-mono text-sm text-signal">
                  <Scramble text={item.rule_id ?? "Guide"} delay={i * 40} duration={420} />
                </span>
                <span>
                  <span className="font-display text-xl font-medium group-hover:text-signal">{item.title}</span>
                  <span className="mt-0.5 block text-sm text-ink-2">{item.summary}</span>
                </span>
              </Link>
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
  // How far through the article you are.
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 200, damping: 30 });
  return (
    <div className="max-w-3xl">
      <Link to="/kb" className="text-sm font-bold text-signal hover:underline">
        ← All articles
      </Link>
      {/* Portalled: a fixed bar inside the animated page container would be pinned to it. */}
      {createPortal(<motion.div aria-hidden="true" className="fixed inset-x-0 top-0 z-30 h-[3px] origin-left bg-highlight" style={{ scaleX: progress }} />, document.body)}
      <article className="prose-kb mt-6">
        {article.isPending ? (
          <LoadingState />
        ) : article.isError ? (
          <ErrorState error={article.error} onRetry={() => void article.refetch()} />
        ) : (
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Links between articles stay inside the app.
              a: ({ href, children }) =>
                href && /^[A-Za-z0-9-]+\.md$/.test(href) ? (
                  <Link to={`/kb/${href.replace(/\.md$/, "")}`}>{children}</Link>
                ) : (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {children}
                  </a>
                ),
            }}
          >
            {article.data}
          </Markdown>
        )}
      </article>
    </div>
  );
}
