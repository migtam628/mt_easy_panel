import type { Metadata } from "next";
import { SessionGate } from "@/components/session-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "MT Panel · Next Preview",
  description: "Private operations dashboard for MT Panel (read-only migration preview)",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body><SessionGate>{children}</SessionGate></body>
    </html>
  );
}
