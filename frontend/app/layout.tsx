import type { Metadata } from "next";
import { Chakra_Petch, IBM_Plex_Mono, Inter } from "next/font/google";
import "./globals.css";

const display = Chakra_Petch({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--fd-src",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--fm-src",
});
const body = Inter({ subsets: ["latin"], variable: "--fb-src" });

export const metadata: Metadata = {
  title: "Competitor Intelligence Engine",
  description:
    "Enter one company URL and get a full competitive-intelligence report in ~90s. Bring your own model key — it never leaves your browser.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable} ${body.variable}`}>
      <body>{children}</body>
    </html>
  );
}
