import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

export const prefersReducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Fade and rise elements as their section scrolls into view.
 * Returns nothing; call it inside a gsap.context so React cleanup reverts it.
 */
export function revealOnScroll(targets, { trigger, stagger = 0.07, y = 22 } = {}) {
  const items = gsap.utils.toArray(targets)
  if (!items.length) return

  if (prefersReducedMotion()) {
    gsap.set(items, { opacity: 1, y: 0 })
    return
  }

  gsap.fromTo(
    items,
    { opacity: 0, y },
    {
      opacity: 1,
      y: 0,
      duration: 0.7,
      ease: 'power2.out',
      stagger,
      scrollTrigger: { trigger: trigger ?? items[0], start: 'top 88%', once: true },
    },
  )
}

/** Slow vertical drift while a section passes through the viewport. */
export function parallax(target, distance = 40) {
  if (!target || prefersReducedMotion()) return

  gsap.fromTo(
    target,
    { y: distance },
    {
      y: -distance,
      ease: 'none',
      scrollTrigger: {
        trigger: target,
        start: 'top bottom',
        end: 'bottom top',
        scrub: 0.6,
      },
    },
  )
}
