import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { revealOnScroll, prefersReducedMotion } from '../lib/reveal'
import './Demo.css'

// Stand-in feed. Deliberately abstract rather than a mock-up of anyone's app —
// the point is the navigation, not the content.
const REELS = ['01', '02', '03', '04', '05', '06']

export default function Demo() {
  const root = useRef(null)
  const strip = useRef(null)

  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const [lastCommand, setLastCommand] = useState(null)

  const atStart = index === 0
  const atEnd = index === REELS.length - 1

  const send = useCallback(
    (command) => {
      if (command === 'PLAY_PAUSE') {
        setLastCommand(command)
        setPaused((p) => !p)
        return
      }
      // A paused reel holds its place; resume before moving off it.
      if (paused) return

      setLastCommand(command)
      setIndex((i) => {
        const next = command === 'NEXT' ? i + 1 : i - 1
        return Math.min(Math.max(next, 0), REELS.length - 1)
      })
    },
    [paused],
  )

  // Drive the strip from the index so the buttons and the keyboard stay in sync.
  useLayoutEffect(() => {
    if (!strip.current) return
    const y = -index * 100
    if (prefersReducedMotion()) {
      gsap.set(strip.current, { yPercent: y })
      return
    }
    gsap.to(strip.current, { yPercent: y, duration: 0.5, ease: 'power3.inOut' })
  }, [index])

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      revealOnScroll('.demo__head > *, .demo__stage', {
        trigger: root.current,
        stagger: 0.08,
      })
    }, root)
    return () => ctx.revert()
  }, [])

  const onKeyDown = (event) => {
    const map = { ArrowUp: 'NEXT', ArrowDown: 'PREVIOUS', ' ': 'PLAY_PAUSE' }
    const command = map[event.key]
    if (!command) return
    event.preventDefault()
    send(command)
  }

  return (
    <section className="section demo" id="demo" ref={root}>
      <div className="container demo__inner">
        <div className="demo__head">
          <p className="eyebrow js-reveal" data-index="02">
            Try it
          </p>
          <h2 className="section-title js-reveal">Press a button. Watch the phone.</h2>
          <p className="lede js-reveal demo__lede">
            The pad below is the mini remote, wired to a phone that only exists on this
            page. It behaves the way the real one does on your desk — and the arrow keys
            work too, once a button has focus.
          </p>
        </div>

        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <div className="demo__stage" onKeyDown={onKeyDown}>
          <div className="demo__phone">
            <div className="device">
              <div className="demo__screen">
                <div className="demo__strip" ref={strip}>
                  {REELS.map((label, i) => (
                    <div className="demo__reel" data-tint={i % 3} key={label}>
                      <span className="demo__reel-index">{label}</span>
                      <span className="demo__reel-note">Reel {label}</span>
                    </div>
                  ))}
                </div>

                {paused && (
                  <span className="demo__paused" aria-hidden="true">
                    Paused
                  </span>
                )}

                <div className="demo__progress">
                  <span
                    key={index}
                    className="demo__progress-bar"
                    data-paused={paused ? 'true' : 'false'}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="demo__remote">
            <p className="demo__remote-title">Mini remote</p>

            <button
              type="button"
              className="demo__btn"
              onClick={() => send('NEXT')}
              disabled={atEnd || paused}
            >
              <span aria-hidden="true">▲</span> Next
            </button>
            <button
              type="button"
              className="demo__btn"
              onClick={() => send('PLAY_PAUSE')}
            >
              {paused ? 'Play' : 'Pause'}
            </button>
            <button
              type="button"
              className="demo__btn"
              onClick={() => send('PREVIOUS')}
              disabled={atStart || paused}
            >
              <span aria-hidden="true">▼</span> Previous
            </button>

            {/* Says why Next and Previous are dead, so they don't read as broken. */}
            <p className="demo__log" role="status">
              {paused
                ? 'Paused — press Play to scroll'
                : lastCommand
                  ? `${lastCommand} sent`
                  : 'Waiting for a command'}
            </p>
            <p className="demo__count">
              Reel {index + 1} of {REELS.length}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
