"use client"

import { useTheme } from "next-themes"
import { useRouter } from "next/navigation"
import { Bell, Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function DashboardHeader({ title }: { title: string }) {
  const { setTheme, resolvedTheme } = useTheme()
  const router = useRouter()

  return (
    <header className="flex h-14 items-center gap-3 border-b bg-card px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />

      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-foreground">{title}</h1>
        <Badge variant="outline" className="hidden sm:inline-flex">
          Phase 4 foundation
        </Badge>
      </div>

      <div className="ml-auto flex items-center gap-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="relative h-8 w-8">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
              <span className="sr-only">Quality signals</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <div className="px-3 py-2">
              <p className="text-sm font-medium text-foreground">Quality signals</p>
              <p className="text-xs text-muted-foreground">Jump to the internal views where feedback, playbook, and reflection signals are inspected.</p>
            </div>
            <DropdownMenuItem onClick={() => router.push("/dashboard")}>
              Dashboard quality summary
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/playbook")}>
              Playbook bullets and candidates
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/feedback")}>
              Feedback store and error labels
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/history")}>
              Version churn and warning history
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/generate")}>
              Generation guardrails and runtime checks
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="h-4 w-4 rotate-0 scale-100 text-muted-foreground transition-transform dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 text-muted-foreground transition-transform dark:rotate-0 dark:scale-100" />
          <span className="sr-only">Toggle theme</span>
        </Button>
      </div>
    </header>
  )
}
