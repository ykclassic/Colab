import type { Metadata } from 'next';
import './globals.css';
import { Nav } from './nav';

export const metadata: Metadata = {
  title: 'Colab Command Center',
  description: 'Operational view of the Colab multi-agent platform',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
