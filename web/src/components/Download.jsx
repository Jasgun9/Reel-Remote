import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { revealOnScroll } from '../lib/reveal'
import { builds, links } from '../config'
import './Download.css'

const TARGETS = [
  { ...builds.windows, href: links.downloadWindows },
  { ...builds.android, href: links.downloadAndroid },
]

export default function Download() {
  const root = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.download__head > *, .target, .download__source', {
        trigger: root.current,
        stagger: 0.07,
      })
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <section className="section download" id="download" ref={root}>
      <div className="container download__inner">
        <div className="download__head">
          <p className="eyebrow js-reveal" data-index="03">
            Get it
          </p>
          <h2 className="section-title js-reveal">Two pieces. One local network.</h2>
          <p className="lede js-reveal download__lede">
            Install the Android app, run the Windows controller, and pair them using the
            token shown by the phone.
          </p>
        </div>

        <ul className="download__targets">
          {TARGETS.map((t) => (
            <li key={t.label}>
              <a className="target js-reveal" href={t.href}>
                <span className="target__label">{t.label}</span>
                <span className="target__file">{t.file}</span>
                <span className="target__meta">
                  {t.size} · {t.req}
                </span>
                <span className="target__arrow" aria-hidden="true">
                  ↓
                </span>
              </a>
            </li>
          ))}
        </ul>

        <p className="download__source js-reveal">
          Prefer to build it yourself? The repository has the Android Studio project and
          the Python controller. <a href={links.source}>View the source →</a>
        </p>
      </div>
    </section>
  )
}
