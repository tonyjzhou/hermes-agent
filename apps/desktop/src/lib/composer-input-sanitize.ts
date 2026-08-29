/**
 * Strip terminal bracketed-paste leaks and repeated artifact tails from composer
 * text before it is shown in the UI or sent to the gateway.
 *
 * Mirrors hermes_cli/input_sanitize.py (CLI/TUI gateway defensive path).
 */

const BRACKETED_PASTE_BOUNDARY_START = /(^|[\s\n>:\])])\[200~/g
const BRACKETED_PASTE_BOUNDARY_END = /\[201~(?=$|[\s\n<[():;.,!?])/g
const BRACKETED_PASTE_DEGRADED_START = /(^|[\s\n>:\])])00~/g
const BRACKETED_PASTE_DEGRADED_END = /01~(?=$|[\s\n<[():;.,!?])/g

// Leaked xterm modifyOtherKeys (ESC[27;mod;cp~ / ^[[27;mod;cp~ / [27;mod;cp~)
const MOK_RE = /(?:\x1b\[|\^\[\[|(?<=[^\w\d])\[|^\[)27;(\d+);(\d+)[~u]/g
// Leaked Kitty CSI-u (ESC[cp;modu / ^[[cp;modu / [cp;modu)
const CSIU_RE = /(?:\x1b\[|\^\[\[|(?<=[^\w\d])\[|^\[)(\d+)(?:;(\d+))?u/g
// Leaked focus reports
const FOCUS_REPORT_RE = /(?:\x1b\[|\^\[\[)[IO]/g
// Leaked non-character CSI sequences
const LEAKED_CSI_OTHER_RE = /(?:\x1b\[|\^\[\[)\d+(?:;\d+)?[~A-Za-z]/g

const DESKTOP_PASTE_ARTIFACT = '~[[e'

/** Decode or strip leaked xterm modifyOtherKeys and Kitty CSI-u escape sequences. */
export function stripOrDecodeLeakedXtermSequences(text: string): string {
  if (!text) {
    return text
  }

  let cleaned = text.replace(MOK_RE, (_, modStr, cpStr) => {
    const mod = parseInt(modStr, 10)
    const cp = parseInt(cpStr, 10)
    if (mod === 2) {
      if ((cp >= 65 && cp <= 90) || (cp >= 97 && cp <= 122)) {
        return String.fromCharCode(cp).toUpperCase()
      }
      if ((cp >= 32 && cp <= 126) || cp >= 160) {
        return String.fromCharCode(cp)
      }
      return ''
    } else if (mod === 0 || mod === 1) {
      if ((cp >= 32 && cp <= 126) || cp >= 160) {
        return String.fromCharCode(cp)
      }
      return ''
    }
    return ''
  })

  cleaned = cleaned.replace(CSIU_RE, (_, cpStr, modStr) => {
    const cp = parseInt(cpStr, 10)
    const mod = modStr !== undefined ? parseInt(modStr, 10) : 1
    if (cp >= 57358 && cp <= 57455) {
      if (cp >= 57399 && cp <= 57408) {
        return String(cp - 57399)
      }
      const kpMap: Record<number, string> = {
        57409: '.',
        57410: '/',
        57411: '*',
        57412: '-',
        57413: '+',
        57415: '=',
        57416: ',',
      }
      return kpMap[cp] ?? ''
    }
    const baseMod = mod >= 64 ? mod % 64 : mod
    if (baseMod === 2) {
      if ((cp >= 65 && cp <= 90) || (cp >= 97 && cp <= 122)) {
        return String.fromCharCode(cp).toUpperCase()
      }
      if ((cp >= 32 && cp <= 126) || cp >= 160) {
        return String.fromCharCode(cp)
      }
      return ''
    } else if (baseMod === 0 || baseMod === 1) {
      if ((cp >= 32 && cp <= 126) || cp >= 160) {
        return String.fromCharCode(cp)
      }
      return ''
    }
    return ''
  })

  cleaned = cleaned.replace(FOCUS_REPORT_RE, '')
  cleaned = cleaned.replace(LEAKED_CSI_OTHER_RE, '')
  return cleaned
}

/** Strip leaked bracketed-paste wrapper markers from user-visible text. */
export function stripLeakedBracketedPasteWrappers(text: string): string {
  if (!text) {
    return text
  }

  let cleaned = text
    // eslint-disable-next-line no-control-regex -- terminal data may contain control chars
    .replace(/\x1b\[200~/g, '')
    // eslint-disable-next-line no-control-regex -- terminal data may contain control chars
    .replace(/\x1b\[201~/g, '')
    .replace(/\^\[\[200~/g, '')
    .replace(/\^\[\[201~/g, '')

  cleaned = cleaned.replace(BRACKETED_PASTE_BOUNDARY_START, '$1')
  cleaned = cleaned.replace(BRACKETED_PASTE_BOUNDARY_END, '')
  cleaned = cleaned.replace(BRACKETED_PASTE_DEGRADED_START, '$1')
  cleaned = cleaned.replace(BRACKETED_PASTE_DEGRADED_END, '')

  return cleaned
}

/** Drop a trailing run of the desktop ~[[e corruption signature (#62557). */
export function collapseRepeatedInputArtifacts(text: string, minRepeats = 4): string {
  if (!text) {
    return text
  }

  const marker = DESKTOP_PASTE_ARTIFACT
  let index = text.length
  let repeatCount = 0

  while (index >= marker.length && text.slice(index - marker.length, index) === marker) {
    repeatCount += 1
    index -= marker.length
  }

  if (repeatCount < minRepeats) {
    return text
  }

  let start = index

  if (start >= 2 && text.slice(start - 2, start) === '[e') {
    start -= 2
  } else if (start >= 1 && text[start - 1] === '[') {
    start -= 1
  }

  return text.slice(0, start)
}

/** Normalize composer text before submit or draft persistence. */
export function sanitizeComposerInput(text: string): string {
  if (!text) {
    return text
  }

  return collapseRepeatedInputArtifacts(
    stripLeakedBracketedPasteWrappers(stripOrDecodeLeakedXtermSequences(text))
  )
}
