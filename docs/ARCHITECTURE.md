# Architecture and design notes

How Reel Remote is put together and why: where the pieces are split, which
trade-offs were made on purpose, and what it deliberately does not do.

If you just want to run it, start with the [README](../README.md).

## Architecture

```
Windows laptop                                    Android phone
┌──────────────────────────────┐                  ┌────────────────────────────────┐
│ Tk main thread               │                  │ MainActivity                   │
│   buttons, mini remote       │                  │   status, IP, token, geometry  │
│   window-focused key binds   │                  │            │  SharedPreferences│
│                              │                  │            ▼                   │
│ keyboard hook                │                  │ ReelAccessibilityService       │
│ WH_MOUSE_LL hook             │   POST /command  │   ├─ CommandServer (sockets)   │
│ on-screen buttons            │   GET  /ping     │   │    auth, limits, routing   │
│         │                    │ ───────────────► │   └─ dispatchGesture()         │
│         ▼                    │                  │            │                   │
│  trigger() → debounce        │ ◄─────────────── │            ▼                   │
│         │                    │   JSON replies   │      the video app             │
│         ▼                    │                  │   (Reels, Shorts, TikTok …)    │
│  command queue → sender      │                  └────────────────────────────────┘
│  heartbeat every 3s          │
└──────────────────────────────┘
```

Two programs, one protocol. Neither has a build-time dependency on the other; the
contract is the four endpoints described under [Protocol](#protocol).

```
android/
  app/src/main/
    java/me/jasgun/reelremote/
      MainActivity.kt              the only screen: status, start/stop, token, geometry
      ReelAccessibilityService.kt  gesture dispatch, foreground tracking, owns the server
      net/CommandServer.kt         HTTP server, token auth, rate limiting, routing
      Prefs.kt                     SharedPreferences: token, port, geometry, switches
      GestureConfig.kt             gesture geometry as screen percentages
      RemoteState.kt               StateFlows the activity renders
      NetUtils.kt                  local IPv4, private-address test, service-enabled test
    res/                           one layout, strings, the accessibility service config
windows/
  reel_remote_controller.py        the whole controller
  requirements.txt
```

## Where the server lives

The listener runs **inside the accessibility service**, not in a foreground
service and not in the activity. This is the single decision the rest of the
Android side follows from.

An enabled accessibility service is already a long-lived, system-bound process.
Hosting the socket there means the listener keeps running while the user is in
Instagram without a persistent notification, without `FOREGROUND_SERVICE`
permission, and without picking a foreground service type — `dataSync` is time
limited on recent Android versions and `specialUse` invites a review
conversation. None of that applies here.

It also couples the two lifecycles correctly. The server is useless without the
gesture capability, so binding its lifetime to the service is not a limitation but
an invariant: `onServiceConnected` starts it if the user had it running,
`onUnbind` stops it. There is no state in which the app is accepting commands it
cannot carry out.

The activity never touches the socket. It calls `startServer()` / `stopServer()`
on `ReelAccessibilityService.instance` and renders `RemoteState`. Both live in the
same process, so that shared object is two `StateFlow`s rather than a bound
service or a broadcast.

## The command server

`CommandServer` is a hand-written HTTP/1.1 server on a plain `ServerSocket`:
accept loop on one thread, a fixed pool of four workers, one request per
connection, `Connection: close`. Around three hundred lines including auth and
rate limiting.

Writing it out was cheaper than the alternative. The app needs three routes, no
TLS, no keep-alive, no chunked encoding and no static files. Pulling in NanoHTTPD
or Ktor to serve that would add a dependency, a transitive tree and a proguard
question to an APK whose entire point is being small. `org.json` ships with
Android, so the parser is free too. The result has **no third-party dependency in
the request path at all**.

The parsing is deliberately strict and bounded, because it is a socket anyone on
the LAN can reach: request lines and headers cap at 4 KB each, at most 40 headers,
bodies at 4 KB, and a 5 second socket timeout. Anything larger is answered and the
connection dropped rather than buffered.

`dispatchGesture()` is asynchronous, so the worker thread posts the gesture to the
main looper and blocks on a `CountDownLatch` until the system reports completion
or the swipe's duration plus 1.5s elapses. That is what lets `POST /command`
return a truthful result instead of an optimistic 200 — a cancelled gesture comes
back as `GESTURE_FAILED`.

## Gestures

Coordinates are stored as **percentages of the screen**, never pixels, so the same
configuration works on any resolution or aspect ratio.

| Setting | Default | Meaning |
|---|---|---|
| Swipe X | 50% | the vertical line the swipe travels along |
| Start Y | 75% | where `NEXT` begins and `PREVIOUS` ends |
| End Y | 25% | where `NEXT` ends and `PREVIOUS` begins |
| Swipe duration | 220 ms | longer is gentler; raise it if a swipe overshoots |
| Tap X / Y | 50% / 50% | where `PLAY_PAUSE` taps |

`PREVIOUS` is `NEXT` with the two Y values exchanged, so there is one swipe
implementation rather than two. Values are clamped to 2–98% and 50–1000 ms on
both read and write, which means a hand-edited preferences file cannot produce a
`GestureDescription` the system will reject.

Screen size crosses an API boundary at 30. On newer devices it comes from
`WindowManager.currentWindowMetrics` reached through a window context built on
the default display; below that, and if that path throws on some OEM build, it
falls back to `Display.getRealMetrics`. The fallback is the only deprecated call
in the project and it is wrapped in the version check plus a `try`.

The tap path draws a one-pixel line rather than a zero-length one. A degenerate
path is rejected outright on some builds, and a single pixel of travel is still
delivered as a tap.

## What the phone checks before it moves

A command is refused, with a distinct error code, when:

- the screen is off (`SCREEN_OFF`) or the keyguard is up (`SCREEN_LOCKED`) —
  gestures would not reach the app behind the lock screen anyway;
- the configured target app, Instagram by default, is not in the foreground
  (`TARGET_NOT_FOREGROUND`). This check is on by default and can be switched off;
- no window change has been observed yet, so the foreground app is genuinely
  unknown (`FOREGROUND_UNKNOWN`) rather than assumed.

**That guard is the only Instagram-specific code in the project.** The gesture
path has no idea what application is in front of it — it dispatches a swipe
between two points and a tap at a third, all expressed as percentages of the
screen. Every full-screen vertical video feed is driven the same way, so TikTok,
YouTube Shorts, Snapchat Spotlight, Reddit and Facebook Reels work without a line
of code changing. Switching the foreground requirement off makes the app entirely
target-agnostic; leaving it on and changing `Prefs.DEFAULT_TARGET_PACKAGE` pins
the guard to a different app instead.

Being blind to the target is the reason it generalises. An implementation that
located the Reel view through the accessibility node tree would be more precise
and would work in exactly one app.

Foreground detection is the one piece of ambient information the app collects, and
it is deliberately the least it can work with. The service declares
`canRetrieveWindowContent="false"` — it *cannot* read the screen — and subscribes
only to `typeWindowStateChanged`. The single field it reads from those events is
`packageName`. It never sees a Reel, a caption, a username or a comment.

That constraint is also why `FOREGROUND_UNKNOWN` exists as a state. Reading the
current foreground app directly would mean requesting window content or usage
stats; refusing the first command until a window change has been seen was the
cheaper trade.

## Protocol

Plain HTTP with JSON both ways, on port 8787 by default.

```
GET  /ping       -> device state                       (token)
POST /command    -> {"token":"…","command":"NEXT"}     (token)
```

The token travels either in an `X-Auth-Token` header or as a `token` field in the
body; both endpoints accept either.

`GET /ping` is what the controller connects with and then polls every three
seconds:

```json
{
  "ok": true, "app": "reelremote", "protocol": 1,
  "accessibility": true, "screen_on": true, "locked": false,
  "foreground_package": "com.instagram.android",
  "target_foreground": true, "require_target_foreground": true,
  "port": 8787
}
```

Errors are a flat envelope — `{"ok": false, "error": "CODE", "message": "…"}` —
carried on a status that matches the class of failure:

| HTTP | `error` | Cause |
|---|---|---|
| 400 | `BAD_JSON`, `BAD_REQUEST`, `UNKNOWN_COMMAND` | malformed body, or not one of the three commands |
| 401 | `UNAUTHORIZED` | wrong or missing token |
| 403 | `FORBIDDEN_NETWORK` | source address is not private |
| 404 / 405 | `NOT_FOUND`, `METHOD_NOT_ALLOWED` | unknown route, or wrong verb |
| 409 | `SCREEN_OFF`, `SCREEN_LOCKED`, `TARGET_NOT_FOREGROUND`, `FOREGROUND_UNKNOWN`, `GESTURE_FAILED` | the phone is not in a state where the gesture makes sense |
| 413 | `PAYLOAD_TOO_LARGE` | body over 4 KB |
| 429 | `RATE_LIMITED`, `AUTH_THROTTLED` | too fast, or too many bad tokens |

`RATE_LIMITED` carries `retry_after_ms`. There is no protocol negotiation: the
controller warns if `protocol` is not 1 and carries on, because every field it
reads has been present since the first version.

## Security

The threat being defended against is specific and small: **another device on the
same Wi-Fi sending swipes to your phone.** A guest, a housemate, a compromised
smart TV. It is not a defence against someone who already controls one of the two
machines.

- **Private networks only.** The source address is tested against RFC1918,
  loopback and link-local ranges *before* the token is examined. A request from a
  routable address gets `403` and never reaches authentication, so a port
  accidentally forwarded on a router still does not expose the command endpoint.
- **Pairing token.** Sixteen characters from a 32-symbol alphabet drawn from
  `SecureRandom` — 80 bits, from an alphabet with `0/O/1/I` removed because it
  gets read off a phone screen and typed on a laptop. Comparison is length-checked
  and then constant-time across the characters.
- **Auth throttling.** Ten failed tokens from one address inside sixty seconds
  and that address is refused for the rest of the window. Guessing 80 bits at ten
  attempts a minute is not a threat model, but it keeps the log quiet.
- **Command rate limiting.** A 150 ms floor between accepted commands and a
  ceiling of 25 in any rolling five seconds. This is as much about the phone as
  about abuse: a held-down arrow key generates key-repeat at around 30/s, and
  every one of those would otherwise become a dispatched gesture.
- **No outbound anything.** The app has `INTERNET` because opening a listening
  socket requires it. It makes no outbound connection, contains no analytics, no
  crash reporter and no update check.
- **`allowBackup="false"`**, so the token does not travel to cloud backup.

Traffic is plain HTTP. On a hostile LAN, ARP spoofing would expose the token.
TLS would mean shipping a certificate the laptop could actually verify, which for
a self-signed cert on a rotating DHCP address means either pinning or teaching
the user to click through a warning. For a three-command remote on a home
network, that complexity buys less than it costs — but it is the first thing to
revisit if this ever ran anywhere else.

## The controller

One Tkinter window, one file, and a threading rule that the rest of it depends on.

**Tk widgets and variables are touched from the main thread only.** Everything
else — connect, heartbeat, network scan, the sender, the `keyboard` hook and the
mouse hook — reports back by putting a message on `ui_queue`, which a
`self.after(80, …)` pump drains on the main thread. Log lines, status changes,
disconnects and recorded hotkeys all travel that way.

Input arrives from five places — window-focused key bindings, global hotkeys,
the mouse wheel, the middle button, and the on-screen buttons — and all five call
`trigger()`. That funnel is where the 200 ms debounce and the six-slot send queue
live, so no input path can flood the phone and none can be starved by another.
The queue drops on overflow rather than growing: a backlog of stale Reel
navigation is worse than a lost press.

The sender thread is the only thing that calls the phone with a command, so
commands are serialised and arrive in the order they were triggered.

### Hotkeys, and why they avoid suppression

`keyboard` hooks a key globally with `suppress=True` — which stops the key
reaching every other application. For a bare `Space` that is mandatory (otherwise
typing a space would also pause the Reel) and also ruinous: while armed you
cannot type a space anywhere on the machine.

Modifier combinations dodge the problem entirely. Nothing types `Ctrl+Alt+Space`
by accident, so the hook does not need to suppress, so it can stay armed all day
without stealing input. That is why the default preset is `Ctrl+Alt` and why
global hotkeys are on by default.

Suppression is therefore **derived, not configured**:

```python
def needs_suppression(combo: str) -> bool:
    return "+" not in combo
```

One rule reproduces both behaviours and extends to custom bindings for free —
bind `j` and it gets swallowed system-wide, bind `ctrl+alt+j` and it does not.
Bindings that steal real keys never arm themselves: selecting them un-ticks the
global switch, and disconnecting releases them.

Recording a custom combo goes through `keyboard.read_hotkey()`, which returns the
same string format that `add_hotkey()` consumes, so a recorded binding is
registrable by construction rather than by validation.

### The mouse wheel

`Alt+Shift`+wheel is a raw `WH_MOUSE_LL` hook installed through `ctypes`, on its
own thread with its own message loop.

The Python mouse libraries were rejected for one concrete reason: **they cannot
suppress an event.** Without suppression, `Alt+Shift`+scroll would advance the
Reel *and* scroll whatever is under the cursor. Returning `1` from the hook
consumes the event, and the hook only does that while exactly the configured
modifier set is held, tested with `GetAsyncKeyState`. Let go and the wheel is
untouched. The cost is about a hundred lines of `ctypes` declarations; the gain
is no new dependency and behaviour that is actually correct.

Two details that are easy to get wrong and are handled: the wheel delta is the
**signed** high word of `mouseData`, so it is read through `c_short` rather than
masked; and both `WM_MBUTTONDOWN` and `WM_MBUTTONUP` are suppressed even though
only the first fires a command, because swallowing half a click leaves
applications holding a button that never comes up.

Function signatures are declared explicitly on every `user32` call. Without
`argtypes`, `ctypes` truncates handles and `LPARAM` pointers to 32 bits on a
64-bit build and the hook misbehaves in ways that do not raise.

Wheel **down** is `NEXT`, matching how a feed scrolls on the web rather than how
a thumb swipes on glass. It is invertible for people who disagree.

## State and configuration

The phone keeps everything in `SharedPreferences`: token, port, gesture geometry,
the foreground requirement, and whether the server was running — which is what
lets it come back by itself when the accessibility service reconnects after a
reboot.

The controller keeps `%APPDATA%\ReelRemote\controller.json`: address, port, token,
preset and custom bindings, wheel settings, always-on-top, and whether the mini
remote was open. Every key falls back individually, so a partial or hand-edited
file degrades to defaults per setting instead of being discarded whole.

The pairing token is stored in that file in the clear. It is a LAN capability
token for three swipe commands, guarded by the file's own directory permissions;
encrypting it would need a key stored next to it.

## Testing

**There is no automated test suite, and that is the largest gap in this project.**

What has been verified, and how:

- The Android project builds clean from the committed source — `./gradlew
  assembleDebug`, 36 tasks, a 5.45 MB debug APK.
- The controller was driven through scripted runs that instantiate the Tk app
  without entering `mainloop()`, pump the event loop, and assert on real state:
  every hotkey preset registers and unregisters without leaking hooks, switching
  to a suppressing preset auto-disarms, buttons enable and disable with the
  connection, the mini remote does not duplicate widgets when reopened and
  deregisters them when closed, and rapid input collapses to a single queued
  command.
- The mouse hook callback was exercised directly with synthetic events to confirm
  signed delta extraction in both directions, suppression only while modifiers are
  held, pass-through otherwise, and that an exception in the callback cannot
  escape into the Windows hook chain.
- Every hotkey combination in every preset was checked against
  `keyboard.parse_hotkey()`.

Those were scripts run during development, not a committed suite, so nothing
guards against regression. The parts worth writing tests for first are the ones
with logic rather than plumbing: `CommandServer`'s routing, auth and rate limiting
against a socket on localhost, `GestureConfig` clamping, and the controller's
`needs_suppression` / `parse_modifiers` / wheel-direction mapping, which are pure
functions already.

## Tradeoffs

**The server lives in the accessibility service.** No notification, no foreground
service type, no possibility of accepting a command the app cannot perform. The
cost is that the listener cannot run with the service switched off — which is not
a real cost, because it would have nothing to do.

**A hand-written HTTP server.** Three routes, no TLS, no keep-alive: a library
would have been more code in the APK than the server is. The cost is that the
parser is mine to get right, which is why it is bounded everywhere and strict
about lengths. If this ever needed TLS or streaming, it should be replaced rather
than extended.

**HTTP rather than WebSocket.** Each command is a self-contained, idempotent
request with a real reply, and there is no stream to keep alive or reconnect.
Liveness comes from a three-second poll instead. The cost is a TCP handshake per
command; on a LAN that is invisible next to the 220 ms the swipe itself takes.

**Gesture geometry, not accessibility node targeting.** Finding the Reel view and
acting on it would be more robust to layout changes — and would require
`canRetrieveWindowContent`, which is exactly the permission this app refuses to
hold. Blind swipes at configurable coordinates keep the privacy claim absolute.
The cost is that the coordinates are tuning, not truth.

**One file for the controller.** A thousand lines is at the upper end of
defensible, and the seams where it would split — client, hooks, UI — are already
visible. It stays one file because it ships as one script and one executable, and
because nothing in it is reused elsewhere. That answer stops being right the
moment a second entry point exists.

**Global hotkeys on by default, bare keys never.** Convenience where it is safe,
deliberate opt-in where it is not, decided by a one-line rule rather than a
setting the user has to understand.

## Limitations

- **The threading rule is not fully enforced.** `_connect_worker`, `_save_config`
  and `_on_wheel` read Tk variables from background threads — and `_on_wheel` runs
  inside the low-level mouse hook, which has a time budget. It works in practice
  and it is wrong in principle; the fix is a plain settings snapshot the workers
  read instead.
- **Network discovery sends the token to every host it probes.** "Find phone"
  walks all 254 addresses on the /24 authenticating against `/ping`, which hands
  the pairing token to whatever answers — including anything hostile listening on
  that port. The fix is an unauthenticated `/discover` route returning nothing but
  `{"app":"reelremote","protocol":1}`, so the scan can identify the phone and the
  token only ever goes to the address the user then connects to.
- **iOS is impossible, not merely unimplemented.** No third-party iOS app can
  inject touches into another app; the sandbox forbids it at the OS level. The
  native equivalents are a Bluetooth mouse paired to the phone with AssistiveTouch
  custom gestures, or Switch Control recipes driven by a Bluetooth keyboard.
- **The phone must be unlocked and awake.** Commands are refused otherwise, by
  design.
- **The target app is not editable in the UI.** The foreground guard reads
  `Prefs.targetPackage`, which is stored and honoured but never surfaced as a
  field, so pinning it to TikTok or YouTube Shorts means editing
  `DEFAULT_TARGET_PACKAGE` and rebuilding. Unticking the guard works for any app
  today; a package field, or a picker over the installed launcher apps, is the
  obvious small addition.
- **Any vertical feed works, but none of them are a stable target.** The
  coordinates work because these apps are full-screen vertical pagers. A layout
  change in any of them could require retuning, and nothing here would detect
  that — the gesture would be dispatched successfully and simply do the wrong
  thing.
- **Gestures are fire-and-forget.** A `200` means the system delivered the swipe,
  not that a Reel advanced. There is no feedback channel, and adding one would
  mean reading the screen.
- **One phone at a time.** The controller holds a single address and token.
- **The APK is unsigned debug output.** Fine for sideloading; distributing it
  would need a release keystore and a signing config.
- **Windows only on the laptop side.** The keyboard hook could be made portable;
  the wheel hook is Win32 by construction and would need a separate
  implementation per platform.
