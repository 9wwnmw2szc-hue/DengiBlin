import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'MarketBrain — Sandbox', description: 'Анализ рынка и контроль торгового риска' };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
