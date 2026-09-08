/**
 * External links.
 *
 * The repository has no git remote configured yet and there is no published
 * release, so these are deliberate placeholders rather than invented URLs.
 * Replace the three strings below once the repo and release exist — nothing
 * else in the site needs changing.
 */
const PLACEHOLDER = '#'

export const links = {
  source: PLACEHOLDER,
  downloadWindows: PLACEHOLDER,
  downloadAndroid: PLACEHOLDER,
}

/** True while a link is still an unreplaced placeholder. */
export const isPlaceholder = (href) => href === PLACEHOLDER

/** Author links. These are real, unlike the release placeholders above. */
export const author = {
  name: 'Jasgun Singh',
  portfolio: 'https://jasgun.me',
  github: 'https://github.com/Jasgun9',
  chai: 'https://buymeachai.ezee.li/Jasgunsingh',
}

/** Build facts, measured from the actual artefacts in this repo. */
export const builds = {
  windows: { label: 'Windows', file: 'ReelRemote.exe', size: '14.6 MB', req: 'Windows 10 or 11' },
  android: { label: 'Android', file: 'app-debug.apk', size: '5.5 MB', req: 'Android 8.0+' },
}
