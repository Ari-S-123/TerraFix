/**
 * Root layout component for the Next.js application.
 * 
 * This component provides the HTML structure and global styles for the entire
 * application. It wraps all pages and ensures consistent styling across routes.
 */

import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Self-Healing Cloud Dashboard',
  description: 'Real-time compliance remediation monitoring',
}

type RootLayoutProps = {
  children: React.ReactNode
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}

