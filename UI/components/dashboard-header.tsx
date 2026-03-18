"use client"

import { useTheme } from "next-themes"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { Bell, Search, Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function DashboardHeader({ title }: { title: string }) {
  const { setTheme, resolvedTheme } = useTheme()
  const router = useRouter()
  const [searchOpen, setSearchOpen] = useState(false)

  return (
    <header className="flex h-14 items-center gap-3 border-b bg-card px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />

      <h1 className="text-sm font-semibold text-foreground">{title}</h1>

      <div className="ml-auto flex items-center gap-1">
        {searchOpen ? (
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search courses, documents, exams..."
              className="h-8 w-56 pl-8 text-sm"
              autoFocus
              onBlur={() => setSearchOpen(false)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setSearchOpen(false)
              }}
            />
          </div>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setSearchOpen(true)}
          >
            <Search className="h-4 w-4 text-muted-foreground" />
            <span className="sr-only">Search</span>
          </Button>
        )}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 relative">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
              <span className="sr-only">Notifications</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <div className="px-3 py-2">
              <p className="text-sm font-medium text-foreground">Notifications</p>
            </div>
            <DropdownMenuItem onClick={() => router.push("/dashboard/history")}>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm">Exam version ready for review</span>
                <span className="text-xs text-muted-foreground">Verifier results and evidence are available in review.</span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/documents")}>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm">Document processed</span>
                <span className="text-xs text-muted-foreground">PDF parsing, sectioning, and indexing completed.</span>
              </div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0 text-muted-foreground" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100 text-muted-foreground" />
          <span className="sr-only">Toggle theme</span>
        </Button>
      </div>
    </header>
  )
}
