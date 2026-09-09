import BrandMark from './BrandMark'
import Byline from './Byline'
import './Footer.css'

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="container">
        <div className="site-footer__top">
          <a className="site-footer__brand" href="#top">
            <BrandMark size={34} />
            <span className="site-footer__name">
              <span className="site-footer__name-accent">Reel</span> Remote
            </span>
          </a>

          <p className="site-footer__note">
            © Reel Remote 2026 — MIT licensed. Drive short-form video on your phone
            from your laptop.
          </p>
        </div>

        <Byline />
      </div>
    </footer>
  )
}
