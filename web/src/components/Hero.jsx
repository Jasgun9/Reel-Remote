import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import controllerImg from '../assets/controller.png'
import phoneImg from '../assets/phone.webp'
import { prefersReducedMotion } from '../lib/reveal'
import './Hero.css'

export default function Hero() {
  const root = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      if (prefersReducedMotion()) {
        gsap.set('.js-reveal, .hero__win, .hero__phone', { opacity: 1, y: 0, x: 0 })
        return
      }

      gsap
        .timeline({ defaults: { ease: 'power3.out' } })
        .fromTo(
          '.hero__copy .js-reveal',
          { opacity: 0, y: 18 },
          { opacity: 1, y: 0, duration: 0.65, stagger: 0.075 },
        )
        .fromTo(
          '.hero__win',
          { opacity: 0, y: 26 },
          { opacity: 1, y: 0, duration: 0.85 },
          0.2,
        )
        .fromTo(
          '.hero__phone',
          { opacity: 0, y: 22, x: -10 },
          { opacity: 1, y: 0, x: 0, duration: 0.7 },
          0.45,
        )
    }, root)

    return () => ctx.revert()
  }, [])

  return (
    <section className="hero" id="top" ref={root}>
      <div className="container hero__inner">
        <div className="hero__copy">
          <p className="hero__tag js-reveal">
            <span className="hero__dot" aria-hidden="true" />
            Android + Windows · local network only
          </p>

          <h1 className="hero__title js-reveal">
            Scroll your phone
            <br />
            from your laptop.
          </h1>

          <p className="hero__sub js-reveal">
            Your phone plays Reels in a stand. Your laptop drives it — arrow keys, the
            mouse wheel, or a floating button pad.
          </p>

          <div className="hero__actions js-reveal">
            <a className="btn btn--primary" href="#download">
              Download
            </a>
            <a className="btn btn--ghost" href="#showcase">
              See it working
            </a>
          </div>

          <ul className="hero__meta js-reveal">
            <li>
              <span>Commands</span>Next · Previous · Play&nbsp;/&nbsp;Pause
            </li>
            <li>
              <span>Reads your screen</span>Never
            </li>
            <li>
              <span>Licence</span>MIT
            </li>
          </ul>
        </div>

        <div className="hero__stage">
          <figure className="hero__win">
            <img
              src={controllerImg}
              alt="The Reel Remote controller on Windows: phone address and pairing token, hotkey preset, and Next, Play/Pause and Previous buttons above an event log."
              width="703"
              height="544"
              loading="eager"
            />
          </figure>

          <figure className="hero__phone">
            <div className="device device--sm">
              <div className="device__screen">
                <img
                  src={phoneImg}
                  alt="The Reel Remote Android app showing the running server, its address and the pairing token."
                  width="720"
                  height="1523"
                  loading="eager"
                />
              </div>
            </div>
          </figure>
        </div>
      </div>
    </section>
  )
}
