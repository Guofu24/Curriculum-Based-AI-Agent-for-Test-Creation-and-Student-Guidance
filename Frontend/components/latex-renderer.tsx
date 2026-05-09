'use client'

import React from 'react'
import 'katex/dist/katex.min.css'
import katex, { type KatexOptions } from 'katex'
import { cn } from '@/lib/utils'

interface LatexRendererProps {
  children: string
  className?: string
  /** If true, treat the whole string as a single display-mode block ($$...$$) */
  block?: boolean
}

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'inline'; value: string }
  | { kind: 'block'; value: string }

/**
 * Splits a mixed text+LaTeX string into segments.
 * Supports:
 *   $$...$$ → display / block math
 *   $...$   → inline math
 *   \[...\] → display math
 *   \(...\) → inline math
 */
function parseSegments(raw: string): Segment[] {
  const segments: Segment[] = []
  // Pattern: $$...$$ | $...$ | \[...\] | \(...\)
  const pattern = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g

  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ kind: 'text', value: raw.slice(lastIndex, match.index) })
    }

    if (match[1] !== undefined || match[2] !== undefined) {
      // Display math ($$...$$ or \[...\])
      segments.push({ kind: 'block', value: (match[1] ?? match[2]).trim() })
    } else if (match[3] !== undefined || match[4] !== undefined) {
      // Inline math ($...$ or \(...\))
      segments.push({ kind: 'inline', value: (match[3] ?? match[4]).trim() })
    }

    lastIndex = pattern.lastIndex
  }

  if (lastIndex < raw.length) {
    segments.push({ kind: 'text', value: raw.slice(lastIndex) })
  }

  return segments
}

const KATEX_OPTIONS: KatexOptions = {
  throwOnError: false,
  strict: 'ignore',
  trust: false,
}

function renderKatex(latex: string, displayMode: boolean): string | null {
  const originalWarn = typeof console !== 'undefined' ? console.warn : undefined

  try {
    if (originalWarn) {
      console.warn = (...args: unknown[]) => {
        const message = args.map(String).join(' ')
        if (
          message.includes('No character metrics') ||
          message.includes('LaTeX-incompatible input')
        ) {
          return
        }
        originalWarn(...args)
      }
    }

    return katex.renderToString(latex, {
      ...KATEX_OPTIONS,
      displayMode,
    })
  } catch {
    return null
  } finally {
    if (originalWarn) {
      console.warn = originalWarn
    }
  }
}

function SafeInlineMath({ latex }: { latex: string }) {
  const html = React.useMemo(() => renderKatex(latex, false), [latex])
  if (!html) {
    return <code className="text-red-500">{`$${latex}$`}</code>
  }

  return <span dangerouslySetInnerHTML={{ __html: html }} />
}

function SafeBlockMath({ latex }: { latex: string }) {
  const html = React.useMemo(() => renderKatex(latex, true), [latex])
  if (!html) {
    return <code className="text-red-500">{`$$${latex}$$`}</code>
  }

  return <div dangerouslySetInnerHTML={{ __html: html }} />
}

export function LatexRenderer({ children, className, block }: LatexRendererProps) {
  if (typeof children !== 'string') return null

  // Whole-block shortcut
  if (block) {
    return (
      <div className={cn('katex-display-wrapper', className)}>
        <SafeBlockMath latex={children} />
      </div>
    )
  }

  const segments = parseSegments(children)

  // Pure text — no math found
  if (segments.length === 1 && segments[0].kind === 'text') {
    return <span className={cn('whitespace-pre-wrap', className)}>{children}</span>
  }

  return (
    <span className={cn('whitespace-pre-wrap leading-relaxed', className)}>
      {segments.map((seg, i) => {
        if (seg.kind === 'text') return <React.Fragment key={i}>{seg.value}</React.Fragment>
        if (seg.kind === 'inline') return <SafeInlineMath key={i} latex={seg.value} />
        return (
          <span key={i} className="my-2 block">
            <SafeBlockMath latex={seg.value} />
          </span>
        )
      })}
    </span>
  )
}
