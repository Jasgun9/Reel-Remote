import { author } from '../config'
import './Byline.css'

/**
 * Author byline row. Sits under the footer's brand row, separated by a rule —
 * the same arrangement used on the Switchboard and QRCraft footers.
 */
export default function Byline() {
  return (
    <div className="byline">
      <span>
        Made by <strong>{author.name}</strong>
      </span>

      <nav aria-label="Links to the author">
        <a href={author.portfolio} target="_blank" rel="me noopener noreferrer">
          Portfolio
        </a>
        <a href={author.github} target="_blank" rel="me noopener noreferrer">
          GitHub
        </a>
        <a href={author.chai} target="_blank" rel="me noopener noreferrer">
          BuyMeChai
        </a>
      </nav>
    </div>
  )
}
