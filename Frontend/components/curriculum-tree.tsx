"use client"

import { useState, useMemo } from "react"
import { ChevronRight, ChevronDown, FolderOpen, FileText } from "lucide-react"
import { cn } from "@/lib/utils"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Save } from "lucide-react"

// ── Flat type from API ──────────────────────────────────────────────────────

interface FlatCurriculumNode {
  id: string
  title: string
  level: number       // 1=chapter, 2=section, 3=subsection
  parent_id?: string | null
  chunk_count?: number
}

// ── Nested type used internally for rendering ────────────────────────────────

interface NestedCurriculumNode {
  id: string
  title: string
  type: "chapter" | "section" | "topic"
  chunk_count?: number
  children?: NestedCurriculumNode[]
}

// ── Transform flat API response → nested tree ──────────────────────────────

function flatToNested(flat: FlatCurriculumNode[]): NestedCurriculumNode[] {
  const nodeMap = new Map<string, NestedCurriculumNode>()
  const roots: NestedCurriculumNode[] = []

  for (const node of flat) {
    const typeMap: Record<number, "chapter" | "section" | "topic"> = {
      1: "chapter",
      2: "section",
      3: "topic",
    }
    nodeMap.set(node.id, {
      id: node.id,
      title: node.title,
      type: typeMap[node.level] ?? "topic",
      chunk_count: node.chunk_count,
      children: [],
    })
  }

  for (const node of flat) {
    const nested = nodeMap.get(node.id)!
    if (node.parent_id && nodeMap.has(node.parent_id)) {
      nodeMap.get(node.parent_id)!.children!.push(nested)
    } else {
      roots.push(nested)
    }
  }

  return roots
}

// ── Props ───────────────────────────────────────────────────────────────────

interface CurriculumTreeProps {
  /** Flat array from GET /documents/{id}/curriculum-tree API */
  nodes: FlatCurriculumNode[]
  selectedIds: string[]
  onSelectionChange: (selectedIds: string[]) => void
  /** Called with flat selected nodes when user clicks Save */
  onSave?: (nodes: FlatCurriculumNode[]) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export function CurriculumTree({
  nodes,
  selectedIds,
  onSelectionChange,
  onSave,
}: CurriculumTreeProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  // Transform flat API data → nested tree for rendering
  const nestedNodes = useMemo(() => flatToNested(nodes), [nodes])

  const toggleExpand = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const getAllChildIds = (node: NestedCurriculumNode): string[] => {
    const ids: string[] = [node.id]
    if (node.children) {
      for (const child of node.children) {
        ids.push(...getAllChildIds(child))
      }
    }
    return ids
  }

  const toggleSelect = (node: NestedCurriculumNode) => {
    const allChildIds = getAllChildIds(node)
    const allSelected = allChildIds.every(id => selectedIds.includes(id))

    let newSelectedIds: string[]
    if (allSelected) {
      newSelectedIds = selectedIds.filter(id => !allChildIds.includes(id))
    } else {
      newSelectedIds = [...new Set([...selectedIds, ...allChildIds])]
    }
    onSelectionChange(newSelectedIds)
  }

  const isIndeterminate = (node: NestedCurriculumNode): boolean => {
    if (!node.children || node.children.length === 0) return false
    const allChildIds = getAllChildIds(node).slice(1)
    const selectedCount = allChildIds.filter(id => selectedIds.includes(id)).length
    return selectedCount > 0 && selectedCount < allChildIds.length
  }

  const renderNode = (node: NestedCurriculumNode, level: number = 0) => {
    const isExpanded = expandedIds.has(node.id)
    const hasChildren = (node.children?.length ?? 0) > 0
    const isSelected = selectedIds.includes(node.id)
    const indeterminate = isIndeterminate(node)

    return (
      <div key={node.id}>
        <div
          className={cn(
            "flex items-center gap-2 py-2 px-2 rounded-lg cursor-pointer transition-colors hover:bg-muted/50",
            isSelected && "bg-primary/10"
          )}
          style={{ paddingLeft: `${level * 20 + 8}px` }}
        >
          {hasChildren ? (
            <button
              onClick={() => toggleExpand(node.id)}
              className="p-0.5 hover:bg-muted rounded"
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          ) : (
            <span className="w-5" />
          )}

          <Checkbox
            checked={indeterminate ? "indeterminate" : isSelected}
            onCheckedChange={() => toggleSelect(node)}
            className={cn(
              "data-[state=checked]:bg-primary data-[state=checked]:border-primary",
              indeterminate && "data-[state=indeterminate]:bg-primary/50"
            )}
          />

          {hasChildren ? (
            <FolderOpen className="h-4 w-4 text-amber-500" />
          ) : (
            <FileText className="h-4 w-4 text-muted-foreground" />
          )}

          <span
            className={cn(
              "text-sm flex-1",
              isSelected ? "text-foreground font-medium" : "text-muted-foreground"
            )}
            onClick={() => toggleSelect(node)}
          >
            {node.title}
          </span>
        </div>

        {hasChildren && isExpanded && (
          <div>
            {node.children!.map(child => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    )
  }

  // ── Save handler ──────────────────────────────────────────────────────────

  const handleSave = () => {
    const buildFlatSelected = (
      ns: NestedCurriculumNode[],
      selected: Set<string>
    ): FlatCurriculumNode[] => {
      const result: FlatCurriculumNode[] = []
      for (const n of ns) {
        if (selected.has(n.id)) {
          result.push({
            id: n.id,
            title: n.title,
            level: n.type === "chapter" ? 1 : n.type === "section" ? 2 : 3,
            parent_id: undefined,
          })
        }
        if (n.children) {
          result.push(...buildFlatSelected(n.children, selected))
        }
      }
      return result
    }

    const selectedSet = new Set(selectedIds)
    const flatSelected = buildFlatSelected(nestedNodes, selectedSet)
    onSave?.(flatSelected)
  }

  return (
    <div className="space-y-0.5">
      {onSave && (
        <div className="flex justify-end mb-3">
          <Button size="sm" onClick={handleSave}>
            <Save className="mr-2 h-4 w-4" />
            Lưu thay đổi
          </Button>
        </div>
      )}
      {nestedNodes.map(node => renderNode(node))}
    </div>
  )
}
