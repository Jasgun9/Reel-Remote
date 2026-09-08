import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { revealOnScroll } from '../lib/reveal'
import './Intro.css'

export default function Intro() {
  const root = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.intro__statement, .intro__note', {
        trigger: root.current,
        stagger: 0.1,
        y: 16,
      })
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <section className="section intro" ref={root}>
      <div className="container intro__inner">
        <p className="intro__statement js-reveal">
          Three commands. A swipe up, a swipe down, a tap in the middle —
          <span> sent over your own Wi-Fi.</span>
        </p>

        <p className="intro__note js-reveal">
          Android only lets an app perform touch gestures through an accessibility
          service. Reel Remote uses one, and declares that it cannot read window
          content — so it dispatches the gesture and learns nothing about what is on
          the display.
        </p>
      </div>
    </section>
  )
}
