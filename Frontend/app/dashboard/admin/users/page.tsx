"use client"

import { useEffect, useState } from 'react'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { UserResponse, adminApi } from '@/lib/api'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/components/auth-provider'
import { useRouter } from 'next/navigation'

export default function AdminUsersPage() {
  const { user } = useAuth()
  const router = useRouter()
  const [users, setUsers] = useState<UserResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (user && user.role !== 'admin') {
      router.push('/dashboard')
      return
    }

    async function fetchUsers() {
      try {
        const response = await adminApi.getUsers(1, 100)
        setUsers(response.items)
      } catch (error) {
        console.error('Failed to fetch users:', error)
      } finally {
        setIsLoading(false)
      }
    }

    if (user?.role === 'admin') {
      fetchUsers()
    }
  }, [user, router])

  if (user?.role !== 'admin') return null

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Quản trị viên' }, { label: 'Người dùng' }]} />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6 max-w-6xl">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Quản lý người dùng</h1>
            <p className="text-muted-foreground">
              Danh sách tài khoản trong hệ thống
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Tài khoản</CardTitle>
              <CardDescription>
                Tất cả tài khoản học sinh, giáo viên và quản trị viên.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-4">
                  {[...Array(5)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Email</TableHead>
                        <TableHead>Tên</TableHead>
                        <TableHead>Vai trò</TableHead>
                        <TableHead>Ngày tạo</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {users.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                            Không có dữ liệu
                          </TableCell>
                        </TableRow>
                      ) : (
                        users.map((u) => (
                          <TableRow key={u.id}>
                            <TableCell className="font-medium">{u.email}</TableCell>
                            <TableCell>{u.full_name || '-'}</TableCell>
                            <TableCell>
                              <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                                {u.role === 'admin' ? 'Quản trị viên' : (u.role === 'student' ? 'Học sinh' : 'Giáo viên')}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {new Date(u.created_at).toLocaleDateString('vi-VN')}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </>
  )
}
