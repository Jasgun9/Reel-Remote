import { useEffect, useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import phoneImg from '../assets/phone.webp'
import controllerImg from '../assets/controller.png'
import miniImg from '../assets/mini.webp'
import demoVideo from '../assets/demo.mp4'
import demoPoster from '../assets/demo-poster.webp'
import { revealOnScroll, parallax, prefersReducedMotion } from '../lib/reveal'
import './Showcase.css'

export default function Showcase() {
  const root = useRef(null)
  const video = useRef(null)

  // Play only once the clip is actually on screen. With a plain autoplay
  // attribute the browser fetches the whole file on page load, which visitors
  // who never scroll this far would pay for. Reduced motion opts out entirely.
  useEffect(() => {
    const el = video.current
    if (!el || prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) el.play().catch(() => {})
        else el.pause()
      },
      { threshold: 0.4 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.showcase__head > *, .showcase__clip', {
        trigger: root.current,
        stagger: 0.08,
      })
      revealOnScroll('.showcase__col', { trigger: '.showcase__stage', stagger: 0.12, y: 26 })
      parallax(root.current?.querySelector('.showcase__phone'), 18)
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <section className="section showcase" id="showcase" ref={root}>
      <div className="container">
        <div className="showcase__head">
          <p className="eyebrow js-reveal" data-index="03">
            Screenshots
          </p>
          <h2 className="section-title js-reveal">Both halves, as they actually look.</h2>
        </div>

        <figure className="showcase__clip js-reveal">
          <video
            ref={video}
            src={demoVideo}
            poster={demoPoster}
            width="1280"
            height="720"
            muted
            loop
            playsInline
            controls
            preload="none"
            aria-label="A phone in a stand playing Reels beside a laptop running the controller. Each keypress on the laptop advances the phone to the next Reel."
          />
          <figcaption>
            Recorded on a desk, not staged in a mock-up — the laptop sends the command and
            the phone moves.
          </figcaption>
        </figure>

        <div className="showcase__stage">
          <figure className="showcase__col showcase__col--phone">
            <div className="showcase__phone">
              <div className="device">
                <div className="device__screen">
                  <img
                    src={phoneImg}
                    alt="The Reel Remote Android app: accessibility service enabled, server running with its IP address and port, the pairing token, and the gesture geometry fields."
                    width="720"
                    height="1523"
                    loading="lazy"
                  />
                </div>
              </div>
            </div>
            <figcaption>
              <span className="showcase__label">Android</span>
              Runs the listener. Shows the pairing token and the gesture geometry.
            </figcaption>
          </figure>

          <figure className="showcase__col showcase__col--desktop">
            <div className="showcase__winwrap">
              <img
                className="showcase__win"
                src={controllerImg}
                alt="The Windows controller: connection fields, hotkey preset, the three command buttons and a timestamped event log."
                width="703"
                height="544"
                loading="lazy"
              />
              <img
                className="showcase__mini"
                src={miniImg}
                alt="The mini remote: a small always-on-top window with Next, Play/Pause and Previous buttons."
                width="178"
                height="227"
                loading="lazy"
              />
            </div>
            <figcaption>
              <span className="showcase__label">Windows</span>
              Holds the controls and sends the commands. The mini remote pins above
              everything else.
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  )
}
