const REPO = 'https://github.com/Jasgun9/Reel-Remote'

/**
 * The download links use GitHub's `releases/latest/download/<asset>` form, which
 * resolves to whatever the newest release is — so publishing a new version does
 * not require touching this file. The asset filenames must stay exactly
 * ReelRemote.apk and ReelRemote.exe.
 */
export const links = {
  source: REPO,
  downloadWindows: `${REPO}/releases/latest/download/ReelRemote.exe`,
  downloadAndroid: `${REPO}/releases/latest/download/ReelRemote.apk`,
  releases: `${REPO}/releases`,
}

/** Author links. */
export const author = {
  name: 'Jasgun Singh',
  portfolio: 'https://jasgun.me',
  github: 'https://github.com/Jasgun9',
  chai: 'https://buymeachai.ezee.li/Jasgunsingh',
}

/** Build facts, measured from the actual signed artefacts in this repo. */
export const builds = {
  windows: { label: 'Windows', file: 'ReelRemote.exe', size: '14.6 MB', req: 'Windows 10 or 11' },
  android: { label: 'Android', file: 'ReelRemote.apk', size: '4.5 MB', req: 'Android 8.0+' },
}
