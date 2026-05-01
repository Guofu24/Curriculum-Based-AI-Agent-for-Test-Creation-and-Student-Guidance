'use client'

import React from 'react'
import 'katex/dist/katex.min.css'
import { InlineMath, BlockMath } from 'react-katex'
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

function SafeInlineMath({ latex }: { latex: string }) {
  try {
    return <InlineMath math={latex} />
  } catch {
    return <code className="text-red-500">{`$${latex}$`}</code>
  }
}

function SafeBlockMath({ latex }: { latex: string }) {
  try {
    return <BlockMath math={latex} />
  } catch {
    return <code className="text-red-500">{`$$${latex}$$`}</code>
  }
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
