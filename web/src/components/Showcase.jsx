import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import phoneImg from '../assets/phone.png'
import controllerImg from '../assets/controller.png'
import miniImg from '../assets/mini.png'
import { revealOnScroll, parallax } from '../lib/reveal'
import './Showcase.css'

export default function Showcase() {
  const root = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.showcase__head > *', { trigger: root.current, stagger: 0.08 })
      revealOnScroll('.showcase__col', { trigger: '.showcase__stage', stagger: 0.12, y: 26 })
      parallax(root.current?.querySelector('.showcase__phone'), 18)
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <section className="section showcase" id="showcase" ref={root}>
      <div className="container">
        <div className="showcase__head">
          <p className="eyebrow js-reveal" data-index="02">
            Screenshots
          </p>
          <h2 className="section-title js-reveal">Both halves, as they actually look.</h2>
        </div>

        <div className="showcase__stage">
          <figure className="showcase__col showcase__col--phone">
            <div className="showcase__phone">
              <div className="device">
                <div className="device__screen">
                  <img
                    src={phoneImg}
                    alt="The Reel Remote Android app: accessibility service enabled, server running with its IP address and port, the pairing token, and the gesture geometry fields."
                    width="1080"
                    height="2284"
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
