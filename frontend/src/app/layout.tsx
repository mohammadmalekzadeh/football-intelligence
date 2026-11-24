import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Football Intelligence — AI Match Lab",
  description: "AI-powered football performance and tactical analytics",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}