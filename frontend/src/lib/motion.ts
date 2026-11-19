/** Shared motion settings. Every animation in the app means something about redaction
 *  or diagnosis, and all of it is skipped under prefers-reduced-motion. */
import type { Transition } from "motion/react";

export const SPRING: Transition = { type: "spring", stiffness: 520, damping: 38, mass: 0.8 };
export const SOFT_SPRING: Transition = { type: "spring", stiffness: 260, damping: 30 };
export const POP: Transition = { type: "spring", stiffness: 700, damping: 22 };
export const EASE_OUT = [0.2, 0.7, 0.2, 1] as const;

export function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}
