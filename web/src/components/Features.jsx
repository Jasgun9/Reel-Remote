import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { revealOnScroll } from '../lib/reveal'
import './Features.css'

const FEATURES = [
  {
    id: '01',
    title: 'Global keyboard shortcuts',
    body: (
      <>
        The default combos use modifiers on purpose. Nothing types{' '}
        <code>Ctrl+Alt+Space</code> by accident, so the hooks never swallow a key from
        the app you are working in — and can stay armed all day.
      </>
    ),
    keys: [
      ['Ctrl', 'Alt', '↑', 'Next'],
      ['Ctrl', 'Alt', '↓', 'Previous'],
      ['Ctrl', 'Alt', 'Space', 'Play / Pause'],
    ],
  },
  {
    id: '02',
    title: 'Mouse wheel control',
    body: (
      <>
        Hold <code>Alt+Shift</code> and scroll; middle-click to pause. The wheel is
        intercepted only while those modifiers are held, so ordinary scrolling is
        untouched.
      </>
    ),
  },
  {
    id: '03',
    title: 'Always-on-top mini remote',
    body: (
      <>
        Three buttons in the window, or a small pad pinned above everything else. They
        grey out while disconnected, so the state is never ambiguous.
      </>
    ),
  },
  {
    id: '04',
    title: 'Local network pairing',
    body: (
      <>
        The phone generates a random token and refuses anything that doesn&rsquo;t
        present it. Requests from outside your local network are rejected before the
        token is even read.
      </>
    ),
  },
  {
    id: '05',
    title: 'Works with any vertical video app',
    body: (
      <>
        Nothing in the gesture path knows what Instagram is — it is a swipe and a tap at
        percentages of the screen. Shorts, TikTok and Reddit answer to the same three
        commands.
      </>
    ),
  },
]

export default function Features() {
  const root = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.features__head > *', { trigger: root.current, stagger: 0.08 })
      revealOnScroll('.feature', { trigger: '.features__list', stagger: 0.06, y: 18 })
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <section className="section features" id="features" ref={root}>
      <div className="container">
        <div className="features__head">
          <p className="eyebrow js-reveal" data-index="01">
            Features
          </p>
          <h2 className="section-title js-reveal">
            Built for one job, and only that job.
          </h2>
        </div>

        <div className="features__list">
          {FEATURES.map((f) => (
            <article className="feature js-reveal" key={f.id}>
              <span className="feature__id" aria-hidden="true">
                {f.id}
              </span>
              <h3 className="feature__title">{f.title}</h3>
              <div className="feature__body">
                <p>{f.body}</p>

                {f.keys && (
                  <ul className="feature__keys">
                    {f.keys.map(([a, b, c, label]) => (
                      <li key={label}>
                        <kbd>{a}</kbd>
                        <kbd>{b}</kbd>
                        <kbd>{c}</kbd>
                        <span>{label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
