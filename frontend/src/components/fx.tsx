/**
 * Motion primitives. Each one stands for something the product does: a secret being
 * removed (Scramble, Stamp), a count of what was removed (RollingNumber), a check that
 * passed (DrawCheck), evidence being pointed at (Spotlight), the one action that matters
 * (Magnetic). All of them settle instantly under prefers-reduced-motion.
 */
import { animate, motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { type ReactNode, type PointerEvent, useEffect, useRef, useState } from "react";
import { POP, SPRING } from "../lib/motion";
import { cx } from "./ui";

const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789+/=";

/** Text that decodes from random glyphs into its real value, left to right. */
export function Scramble({ text, delay = 0, duration = 700, className }: { text: string; delay?: number; duration?: number; className?: string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? text : "");
  useEffect(() => {
    if (reduce) {
      setShown(text);
      return;
    }
    let frame = 0;
    let start = 0;
    const timer = window.setTimeout(() => {
      const step = (now: number) => {
        if (!start) start = now;
        const t = Math.min(1, (now - start) / duration);
        const fixed = Math.floor(t * text.length);
        let out = text.slice(0, fixed);
        for (let i = fixed; i < text.length; i++) out += text[i] === " " ? " " : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
        setShown(out);
        if (t < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    }, delay);
    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(frame);
    };
  }, [text, delay, duration, reduce]);
  return (
    <span className={className} aria-label={text}>
      <span aria-hidden="true">{shown || " "}</span>
    </span>
  );
}

/** A number whose digits roll into place like a counter. */
export function RollingNumber({ value, className }: { value: number; className?: string }) {
  const digits = String(Math.max(0, Math.round(value))).split("");
  return (
    <span className={cx("inline-flex overflow-hidden tabular-nums", className)} aria-label={String(value)}>
      {digits.map((d, i) => (
        <Digit key={`${digits.length}-${i}`} digit={Number(d)} index={i} />
      ))}
    </span>
  );
}

function Digit({ digit, index }: { digit: number; index: number }) {
  const reduce = useReducedMotion();
  return (
    <span aria-hidden="true" className="relative inline-block h-[1.15em] w-[0.62em] overflow-hidden">
      <motion.span
        className="absolute inset-x-0 top-0 flex flex-col items-center"
        initial={reduce ? false : { y: "0em" }}
        animate={{ y: `${-digit * 1.15}em` }}
        transition={{ type: "spring", stiffness: 140, damping: 20, delay: reduce ? 0 : index * 0.06 }}
      >
        {Array.from({ length: 10 }, (_, n) => (
          <span key={n} className="block h-[1.15em] leading-[1.15em]">
            {n}
          </span>
        ))}
      </motion.span>
    </span>
  );
}

/**
 * A secret being removed: random glyphs (the value we never keep) are covered by the
 * redaction bar, which then shows its marker id. Driven by real marker ids.
 */
export function Stamp({ marker, delay = 0, length = 14 }: { marker: string; delay?: number; length?: number }) {
  const reduce = useReducedMotion();
  const [stamped, setStamped] = useState(!!reduce);
  useEffect(() => {
    if (reduce) return;
    const timer = window.setTimeout(() => setStamped(true), delay + 420);
    return () => window.clearTimeout(timer);
  }, [delay, reduce]);
  return (
    <span className="relative inline-flex items-center align-baseline">
      <span aria-hidden="true" className={cx("font-mono text-ink-4 transition-opacity duration-150", stamped && "opacity-0")}>
        <Scramble text={"•".repeat(length)} delay={delay} duration={400} />
      </span>
      {stamped && (
        <motion.mark
          className="redaction absolute left-0"
          initial={reduce ? false : { scaleX: 0.2, scaleY: 1.6, opacity: 0 }}
          animate={{ scaleX: 1, scaleY: 1, opacity: 1 }}
          transition={POP}
          style={{ transformOrigin: "left center" }}
        >
          <Scramble text={marker} duration={420} />
        </motion.mark>
      )}
    </span>
  );
}

/** A check mark drawn as a stroke: a rule that ran and found nothing. */
export function DrawCheck({ delay = 0, className }: { delay?: number; className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={cx("h-4 w-4", className)} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <motion.path d="M3 8.5l3.2 3L13 4.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, delay, ease: "easeOut" }} />
    </svg>
  );
}

/** A soft light that follows the pointer across evidence (findings, cases). */
export function Spotlight({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  function move(e: PointerEvent<HTMLDivElement>) {
    const r = ref.current?.getBoundingClientRect();
    if (!r || !ref.current) return;
    ref.current.style.setProperty("--x", `${e.clientX - r.left}px`);
    ref.current.style.setProperty("--y", `${e.clientY - r.top}px`);
  }
  return (
    <div ref={ref} onPointerMove={move} className={cx("spotlight", className)} {...rest}>
      {children}
    </div>
  );
}

/** The primary action leans toward the pointer, then springs back. */
export function Magnetic({ children, strength = 0.25 }: { children: ReactNode; strength?: number }) {
  const reduce = useReducedMotion();
  const x = useSpring(useMotionValue(0), SPRING as { stiffness: number; damping: number });
  const y = useSpring(useMotionValue(0), SPRING as { stiffness: number; damping: number });
  const ref = useRef<HTMLSpanElement>(null);
  return (
    <motion.span
      ref={ref}
      className="inline-flex"
      style={reduce ? undefined : { x, y }}
      onPointerMove={(e) => {
        if (reduce || !ref.current) return;
        const r = ref.current.getBoundingClientRect();
        x.set((e.clientX - (r.left + r.width / 2)) * strength);
        y.set((e.clientY - (r.top + r.height / 2)) * strength);
      }}
      onPointerLeave={() => {
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </motion.span>
  );
}

/** A section wiped into view (clip-path) when it scrolls in. */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div
      className={className}
      initial={{ clipPath: "inset(0 0 100% 0)", y: 12 }}
      whileInView={{ clipPath: "inset(0 0 0% 0)", y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.5, delay, ease: [0.2, 0.7, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}

/** Animate a value from 0 to `to` (for bars and progress). */
export function useAnimatedNumber(to: number, duration = 0.6): number {
  const reduce = useReducedMotion();
  const [value, setValue] = useState(reduce ? to : 0);
  useEffect(() => {
    if (reduce) {
      setValue(to);
      return;
    }
    const controls = animate(0, to, { duration, ease: [0.2, 0.7, 0.2, 1], onUpdate: setValue });
    return () => controls.stop();
  }, [to, duration, reduce]);
  return value;
}
