"use client"

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldGroup, Field, FieldLabel, FieldError } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { GraduationCap, Sparkles, BookOpen, CheckCircle2, AlertCircle } from 'lucide-react'
import { authApi } from '@/lib/api'
import { useAuth } from '@/components/auth-provider'

export default function AuthPage() {
  const router = useRouter()
  const { refreshUser } = useAuth()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  
  // Login form state
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  
  // Register form state
  const [registerEmail, setRegisterEmail] = useState('')
  const [registerPassword, setRegisterPassword] = useState('')
  const [registerName, setRegisterName] = useState('')

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsLoading(true)

    try {
      await authApi.login({ email: loginEmail, password: loginPassword })
      await refreshUser()
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Đăng nhập thất bại. Vui lòng thử lại.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setIsLoading(true)

    if (registerPassword.length < 8) {
      setError('Mật khẩu phải có ít nhất 8 ký tự')
      setIsLoading(false)
      return
    }

    try {
      await authApi.register({
        email: registerEmail,
        password: registerPassword,
        full_name: registerName || undefined,
      })
      setSuccess('Đăng ký thành công! Vui lòng đăng nhập.')
      setRegisterEmail('')
      setRegisterPassword('')
      setRegisterName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Đăng ký thất bại. Vui lòng thử lại.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left Panel - Branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-primary/10 via-background to-accent/10 relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-primary/20 via-transparent to-transparent" />
        
        <div className="relative z-10 flex flex-col justify-center px-16 py-12">
          {/* Logo */}
          <div className="flex items-center gap-3 mb-12">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <GraduationCap className="h-7 w-7" />
            </div>
            <span className="text-3xl font-bold tracking-tight">ExamAI</span>
          </div>

          {/* Hero */}
          <h1 className="text-4xl font-bold tracking-tight text-balance mb-6">
            Tạo đề thi tự động
            <br />
            <span className="text-primary">bằng AI thông minh</span>
          </h1>
          
          <p className="text-lg text-muted-foreground mb-12 max-w-md">
            Hệ thống tạo đề thi từ tài liệu giảng dạy với multi-agent AI pipeline và kiểm soát chất lượng human-in-the-loop.
          </p>

          {/* Features */}
          <div className="space-y-4">
            <FeatureItem 
              icon={<BookOpen className="h-5 w-5" />}
              title="Upload tài liệu"
              description="Hỗ trợ PDF, DOCX, PPTX"
            />
            <FeatureItem 
              icon={<Sparkles className="h-5 w-5" />}
              title="AI sinh đề tự động"
              description="Phân loại theo Bloom Taxonomy"
            />
            <FeatureItem 
              icon={<CheckCircle2 className="h-5 w-5" />}
              title="Kiểm soát chất lượng"
              description="3 checkpoint duyệt đề"
            />
          </div>
        </div>

        {/* Decorative elements */}
        <div className="absolute bottom-0 right-0 w-96 h-96 bg-primary/5 rounded-full blur-3xl" />
        <div className="absolute top-20 right-20 w-64 h-64 bg-accent/10 rounded-full blur-2xl" />
      </div>

      {/* Right Panel - Auth Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-background">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center justify-center gap-2 mb-8">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <GraduationCap className="h-6 w-6" />
            </div>
            <span className="text-2xl font-bold">ExamAI</span>
          </div>

          <Card className="border-0 shadow-xl bg-card/50 backdrop-blur-sm">
            <CardHeader className="space-y-1 pb-4">
              <CardTitle className="text-2xl font-bold text-center">
                Chào mừng
              </CardTitle>
              <CardDescription className="text-center">
                Đăng nhập hoặc tạo tài khoản để bắt đầu
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Tabs defaultValue="login" className="w-full">
                <TabsList className="grid w-full grid-cols-2 mb-6">
                  <TabsTrigger value="login">Đăng nhập</TabsTrigger>
                  <TabsTrigger value="register">Đăng ký</TabsTrigger>
                </TabsList>

                {error && (
                  <Alert variant="destructive" className="mb-4">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}

                {success && (
                  <Alert className="mb-4 border-primary/50 bg-primary/10">
                    <CheckCircle2 className="h-4 w-4 text-primary" />
                    <AlertDescription className="text-primary">{success}</AlertDescription>
                  </Alert>
                )}

                <TabsContent value="login">
                  <form onSubmit={handleLogin} className="space-y-4">
                    <FieldGroup>
                      <Field>
                        <FieldLabel htmlFor="login-email">Email</FieldLabel>
                        <Input
                          id="login-email"
                          type="email"
                          placeholder="teacher@school.edu.vn"
                          value={loginEmail}
                          onChange={(e) => setLoginEmail(e.target.value)}
                          required
                          disabled={isLoading}
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="login-password">Mật khẩu</FieldLabel>
                        <Input
                          id="login-password"
                          type="password"
                          placeholder="Nhập mật khẩu"
                          value={loginPassword}
                          onChange={(e) => setLoginPassword(e.target.value)}
                          required
                          disabled={isLoading}
                        />
                      </Field>
                    </FieldGroup>

                    <Button type="submit" className="w-full" disabled={isLoading}>
                      {isLoading ? (
                        <>
                          <Spinner className="mr-2" />
                          Đang đăng nhập...
                        </>
                      ) : (
                        'Đăng nhập'
                      )}
                    </Button>
                  </form>
                </TabsContent>

                <TabsContent value="register">
                  <form onSubmit={handleRegister} className="space-y-4">
                    <FieldGroup>
                      <Field>
                        <FieldLabel htmlFor="register-name">Họ và tên</FieldLabel>
                        <Input
                          id="register-name"
                          type="text"
                          placeholder="Nguyễn Văn A"
                          value={registerName}
                          onChange={(e) => setRegisterName(e.target.value)}
                          disabled={isLoading}
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="register-email">Email</FieldLabel>
                        <Input
                          id="register-email"
                          type="email"
                          placeholder="teacher@school.edu.vn"
                          value={registerEmail}
                          onChange={(e) => setRegisterEmail(e.target.value)}
                          required
                          disabled={isLoading}
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="register-password">Mật khẩu</FieldLabel>
                        <Input
                          id="register-password"
                          type="password"
                          placeholder="Ít nhất 8 ký tự"
                          value={registerPassword}
                          onChange={(e) => setRegisterPassword(e.target.value)}
                          required
                          minLength={8}
                          disabled={isLoading}
                        />
                        <FieldError>Mật khẩu phải có ít nhất 8 ký tự</FieldError>
                      </Field>
                    </FieldGroup>

                    <Button type="submit" className="w-full" disabled={isLoading}>
                      {isLoading ? (
                        <>
                          <Spinner className="mr-2" />
                          Đang đăng ký...
                        </>
                      ) : (
                        'Đăng ký'
                      )}
                    </Button>
                  </form>
                </TabsContent>
              </Tabs>

              <p className="mt-6 text-center text-sm text-muted-foreground">
                Bằng việc tiếp tục, bạn đồng ý với{' '}
                <a href="#" className="text-primary hover:underline">
                  Điều khoản sử dụng
                </a>{' '}
                và{' '}
                <a href="#" className="text-primary hover:underline">
                  Chính sách bảo mật
                </a>
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function FeatureItem({ 
  icon, 
  title, 
  description 
}: { 
  icon: React.ReactNode
  title: string
  description: string 
}) {
  return (
    <div className="flex items-start gap-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {icon}
      </div>
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
