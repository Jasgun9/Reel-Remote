import { useEffect, useState } from 'react'
import { links } from '../config'
import './Navbar.css'

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`nav ${scrolled ? 'nav--scrolled' : ''}`}>
      <div className="container nav__inner">
        <a className="nav__brand" href="#top">
          <span className="brand-mark" aria-hidden="true" />
          Reel Remote
        </a>

        <nav className="nav__links" aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#showcase">Screenshots</a>
          <a href={links.source}>Source</a>
        </nav>

        <a className="btn btn--primary nav__cta" href="#download">
          Download
        </a>
      </div>
    </header>
  )
}
