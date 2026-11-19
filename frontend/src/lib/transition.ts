/** Route changes through the View Transitions API, so shared elements (a case's file
 *  name) morph from one page into the next. Plain navigation where unsupported or
 *  when reduced motion is asked for. */
import { useCallback } from "react";
import { flushSync } from "react-dom";
import { useNavigate } from "react-router-dom";
import { reducedMotion } from "./motion";

type StartViewTransition = (update: () => void) => unknown;

export function useTransitionNavigate(): (to: string) => void {
  const navigate = useNavigate();
  return useCallback(
    (to: string) => {
      const start = (document as Document & { startViewTransition?: StartViewTransition }).startViewTransition;
      if (!start || reducedMotion()) {
        navigate(to);
        return;
      }
      start.call(document, () => flushSync(() => navigate(to)));
    },
    [navigate],
  );
}

/** The view-transition name that ties a case's title together across pages. */
export function caseTitle(id: string): React.CSSProperties {
  return { viewTransitionName: `case-${id.replace(/[^a-zA-Z0-9-]/g, "")}` } as React.CSSProperties;
}
