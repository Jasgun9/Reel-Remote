/**
 * The app's launcher icon, traced from
 * android/app/src/main/res/drawable/ic_launcher_foreground.xml over
 * ic_launcher_background (#1E1E2E) — the same mark the APK, the Windows
 * executable and the favicon all use.
 *
 * The viewBox is cropped to the adaptive icon's 72x72 safe zone so the arrow
 * fills the tile the way a launcher renders it, rather than sitting inset.
 */
export default function BrandMark({ size = 20 }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="18 18 72 72"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="18" y="18" width="72" height="72" rx="16" fill="#1E1E2E" />
      <path d="M54,28 L70,46 L61,46 L61,62 L47,62 L47,46 L38,46 Z" fill="#fff" />
      <path d="M40,70 L68,70 L68,79 L40,79 Z" fill="#fff" />
    </svg>
  )
}
